"""Daily reminders for customers and assigned staff.

A once-a-day cron queues a reminder for every confirmed booking and every staff
assignment that starts tomorrow ("day_before") or later today ("same_day"),
with days measured in the operator's own time zone. Each reminder is an outbox
job keyed by (entity, kind), so a duplicated or repeated cron run can never
queue the same reminder twice; sending re-checks the window so a retried
day-before reminder is never delivered on the day itself.
"""

import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import (
    Booking,
    GHLInstallation,
    Operator,
    OperatorSettings,
    OutboxJob,
    Staff,
    StaffAssignment,
)
from app.utils.timezone import local_datetime, require_timezone

KINDS = ("day_before", "same_day")


def reminder_windows(now: datetime, time_zone: str) -> dict[str, tuple[datetime, datetime]]:
    """Start-time windows for reminders sent at `now`, as [start, end) instants.

    same_day covers the rest of today, so anything already under way is left
    alone; day_before covers all of tomorrow. Days are operator-local, so a DST
    change day is 23 or 25 hours long.
    """
    today = now.astimezone(require_timezone(time_zone)).date()
    # Normalized to UTC: Python compares and subtracts two datetimes sharing a
    # ZoneInfo by wall-clock time, which is wrong across a DST change.
    tomorrow = local_datetime(today + timedelta(days=1), time(0), time_zone).astimezone(UTC)
    day_after = local_datetime(today + timedelta(days=2), time(0), time_zone).astimezone(UTC)
    return {"same_day": (now.astimezone(UTC), tomorrow), "day_before": (tomorrow, day_after)}


def reminder_still_due(kind: str, start_at: datetime, now: datetime, time_zone: str) -> bool:
    window_start, window_end = reminder_windows(now, time_zone)[kind]
    return window_start <= start_at < window_end


class ReminderService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings

    def enqueue(self, now: datetime | None = None) -> dict[str, int]:
        now = now or datetime.now(UTC)
        counts = {"customer_reminders_queued": 0, "staff_reminders_queued": 0}
        if self.settings is not None and not self.settings.ghl_notifications_enabled:
            return counts
        operators = self.db.execute(
            select(Operator, OperatorSettings.confirmation_email_enabled)
            .outerjoin(OperatorSettings, OperatorSettings.operator_id == Operator.id)
            .where(
                Operator.is_active.is_(True),
                exists().where(
                    GHLInstallation.operator_id == Operator.id,
                    GHLInstallation.is_installed.is_(True),
                ),
            )
        ).all()
        for operator, customer_emails_enabled in operators:
            for kind, (start, end) in reminder_windows(now, operator.time_zone).items():
                # Customer reminders follow the operator's customer-email switch.
                if customer_emails_enabled is not False:
                    bookings = self.db.execute(
                        select(Booking.id, Booking.booking_order_id).where(
                            Booking.operator_id == operator.id,
                            Booking.status == "confirmed",
                            Booking.start_at >= start,
                            Booking.start_at < end,
                        )
                    )
                    for booking_id, order_id in bookings:
                        counts["customer_reminders_queued"] += self._queue(
                            operator.id,
                            "ghl_booking_reminder",
                            f"booking:{booking_id}:reminder:{kind}",
                            {"booking_id": str(booking_id), "kind": kind},
                            order_id=order_id,
                        )
                assignments = self.db.scalars(
                    select(StaffAssignment.id)
                    .join(Staff, Staff.id == StaffAssignment.staff_id)
                    .where(
                        StaffAssignment.operator_id == operator.id,
                        Staff.deleted_at.is_(None),
                        Staff.is_active.is_(True),
                        Staff.email.is_not(None),
                        Staff.email != "",
                        StaffAssignment.start_at >= start,
                        StaffAssignment.start_at < end,
                    )
                )
                for assignment_id in assignments:
                    counts["staff_reminders_queued"] += self._queue(
                        operator.id,
                        "ghl_staff_reminder",
                        f"assignment:{assignment_id}:reminder:{kind}",
                        {"assignment_id": str(assignment_id), "kind": kind},
                    )
        self.db.commit()
        return counts

    def _queue(
        self,
        operator_id: uuid.UUID,
        job_type: str,
        key: str,
        payload: dict[str, Any],
        *,
        order_id: uuid.UUID | None = None,
    ) -> int:
        result = self.db.execute(
            insert(OutboxJob)
            .values(
                operator_id=operator_id,
                booking_order_id=order_id,
                job_type=job_type,
                idempotency_key=key,
                payload=payload,
                status="pending",
            )
            .on_conflict_do_nothing(index_elements=[OutboxJob.idempotency_key])
            # rowcount is unreliable here (psycopg reports -1); a returned id is not.
            .returning(OutboxJob.id)
        )
        return 1 if result.scalar_one_or_none() is not None else 0
