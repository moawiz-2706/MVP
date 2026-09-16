import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import BookingOrder, OutboxJob
from app.services.ghl_contact_service import GHLContactService
from app.services.ghl_email_service import GHLEmailService
from app.services.stripe_transfer_service import StripeTransferService


class OutboxService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def process(self, limit: int = 20) -> dict[str, int]:
        now = datetime.now(UTC)
        stale = now - timedelta(minutes=15)
        jobs = list(
            self.db.scalars(
                select(OutboxJob)
                .where(
                    or_(
                        (
                            OutboxJob.status.in_(["pending", "failed"])
                            & or_(OutboxJob.next_attempt_at.is_(None), OutboxJob.next_attempt_at <= now)
                        ),
                        (OutboxJob.status == "processing") & (OutboxJob.updated_at < stale),
                    )
                )
                .order_by(OutboxJob.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        ids = [job.id for job in jobs]
        for job in jobs:
            job.status = "processing"
            job.attempt_count += 1
            job.updated_at = now
        self.db.commit()

        completed = failed = 0
        for job_id in ids:
            job = self.db.get(OutboxJob, job_id)
            if job is None:
                continue
            try:
                self._run(job)
                job.status = "completed"
                job.last_error = None
                job.next_attempt_at = None
                completed += 1
            except Exception as exc:
                self.db.rollback()
                job = self.db.get(OutboxJob, job_id)
                if job is None:
                    continue
                job.status = "failed"
                job.last_error = str(exc)[:2000]
                delay_minutes = min(24 * 60, 2 ** min(job.attempt_count, 10))
                job.next_attempt_at = datetime.now(UTC) + timedelta(minutes=delay_minutes)
                failed += 1
                if job.booking_order_id:
                    order = self.db.get(BookingOrder, job.booking_order_id)
                    if order and job.job_type == "ghl_upsert_contact":
                        order.ghl_contact_sync_status = "failed"
                    elif order and job.job_type == "ghl_send_confirmation_email":
                        order.ghl_confirmation_email_status = "failed"
            self.db.commit()
        return {"claimed": len(ids), "completed": completed, "failed": failed}

    def drain(self, *, budget_seconds: float, batch: int = 20) -> dict[str, int]:
        """Process batches until nothing is ready or the time budget is spent.

        Failed jobs are rescheduled into the future, so they are not re-claimed
        within the same drain.
        """
        started = time.monotonic()
        totals = {"claimed": 0, "completed": 0, "failed": 0}
        while time.monotonic() - started < budget_seconds:
            result = self.process(limit=batch)
            for key in totals:
                totals[key] += result[key]
            if result["claimed"] < batch:
                break
        return totals

    def _run(self, job: OutboxJob) -> None:
        payload = job.payload or {}
        if job.job_type == "ghl_booking_reminder":
            GHLEmailService(self.db, job.operator_id).send_booking_reminder(
                uuid.UUID(payload["booking_id"]), payload["kind"]
            )
            return
        if job.job_type == "ghl_upsert_staff_contact":
            GHLContactService(self.db, job.operator_id).sync_staff(uuid.UUID(payload["staff_id"]))
            return
        if job.job_type == "ghl_staff_assigned_email":
            GHLEmailService(self.db, job.operator_id).send_staff_assigned(
                uuid.UUID(payload["assignment_id"])
            )
            return
        if job.job_type == "ghl_staff_reminder":
            GHLEmailService(self.db, job.operator_id).send_staff_reminder(
                uuid.UUID(payload["assignment_id"]), payload["kind"]
            )
            return
        if job.job_type == "ghl_staff_unassigned_email":
            GHLEmailService(self.db, job.operator_id).send_staff_unassigned(payload)
            return
        if job.booking_order_id is None:
            raise RuntimeError("Outbox job has no booking order")
        if job.job_type == "stripe_create_transfer":
            StripeTransferService(self.db, self.settings).create_for_order(job.booking_order_id)
        elif job.job_type == "ghl_upsert_contact":
            GHLContactService(self.db, job.operator_id).sync(job.booking_order_id)
        elif job.job_type == "ghl_send_confirmation_email":
            GHLEmailService(self.db, job.operator_id).send(job.booking_order_id)
        else:
            raise RuntimeError(f"Unsupported outbox job type: {job.job_type}")

