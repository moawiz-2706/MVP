from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.entities import (
    Booking,
    BookingOrder,
    GHLAppointmentMapping,
    GHLSyncAttempt,
    GHLSyncRun,
)
from app.services.ghl_appointment_service import GHLAppointmentService
from app.services.ghl_client import GHLAPIError
from app.services.ghl_contact_service import GHLContactService


RETRY_DELAYS_SECONDS = (0.5, 1.0)


@dataclass(frozen=True, slots=True)
class GHLSyncResult:
    run_id: uuid.UUID
    status: str
    attempts: int
    contact_id: str | None
    appointment_ids: tuple[str, ...]
    error_code: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "attempts": self.attempts,
            "contact_id": self.contact_id,
            "appointment_ids": list(self.appointment_ids),
            "error_code": self.error_code,
            "error": self.error,
        }


class GHLSyncService:
    """Synchronize one Passport order to GHL immediately after local commit.

    This service deliberately does not enqueue work. It records a durable run and
    each provider attempt before making network calls, then performs at most
    three short-lived synchronous attempts. Booking/payment state remains local
    and is never rolled back because GHL is unavailable.
    """

    def __init__(
        self,
        db: Session,
        operator_id: uuid.UUID,
        *,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")
        self.db = db
        self.operator_id = operator_id
        self.max_attempts = max_attempts
        self.sleep = sleep

    def _order_bundle(self, order_id: uuid.UUID) -> tuple[BookingOrder, list[Booking]]:
        order = self.db.scalar(
            select(BookingOrder).where(
                BookingOrder.id == order_id,
                BookingOrder.operator_id == self.operator_id,
            )
        )
        if order is None:
            raise ValueError("GHL sync order not found")
        bookings = list(
            self.db.scalars(
                select(Booking)
                .where(
                    Booking.booking_order_id == order.id,
                    Booking.operator_id == self.operator_id,
                )
                .order_by(Booking.start_at, Booking.id)
            )
        )
        if not bookings:
            raise ValueError("GHL sync order has no bookings")
        return order, bookings

    def _new_run(
        self,
        order: BookingOrder,
        trigger_type: str,
        requested_by_user_id: uuid.UUID | None,
    ) -> GHLSyncRun:
        run = GHLSyncRun(
            operator_id=self.operator_id,
            booking_order_id=order.id,
            trigger_type=trigger_type,
            status="running",
            max_attempts=self.max_attempts,
            started_at=datetime.now(UTC),
            requested_by_user_id=requested_by_user_id,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def _start_attempt(
        self,
        run: GHLSyncRun,
        *,
        attempt_number: int,
        entity_type: str,
        operation: str,
        booking_id: uuid.UUID | None = None,
    ) -> GHLSyncAttempt:
        attempt = GHLSyncAttempt(
            run_id=run.id,
            operator_id=self.operator_id,
            booking_order_id=run.booking_order_id,
            booking_id=booking_id,
            entity_type=entity_type,
            operation=operation,
            attempt_number=attempt_number,
            status="started",
            started_at=datetime.now(UTC),
        )
        self.db.add(attempt)
        self.db.commit()
        self.db.refresh(attempt)
        return attempt

    def _finish_attempt(
        self,
        attempt: GHLSyncAttempt,
        *,
        status: str,
        remote_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        provider_http_status: int | None = None,
    ) -> None:
        attempt.status = status
        attempt.remote_id = remote_id
        attempt.error_code = error_code
        attempt.error_message = error_message[:2000] if error_message else None
        attempt.provider_http_status = provider_http_status
        attempt.completed_at = datetime.now(UTC)
        self.db.commit()

    @staticmethod
    def _error_details(exc: Exception) -> tuple[str, int | None, str]:
        provider_status = getattr(exc, "status_code", None)
        if isinstance(exc, GHLAPIError):
            if provider_status == 429:
                code = "ghl_rate_limited"
            elif provider_status is not None and provider_status >= 500:
                code = "ghl_provider_unavailable"
            elif provider_status in {400, 401, 403, 404, 422}:
                code = "ghl_request_rejected"
            else:
                code = "ghl_provider_error"
        else:
            code = "ghl_sync_error"
        return code, provider_status, str(exc)[:2000]

    def _set_run_error(self, run: GHLSyncRun, exc: Exception) -> tuple[str, str]:
        code, provider_status, message = self._error_details(exc)
        run.last_error_code = code
        run.last_error = message
        run.last_http_status = provider_status
        self.db.commit()
        return code, message

    def _succeed(self, run: GHLSyncRun, contact_id: str | None, appointment_ids: list[str]) -> GHLSyncResult:
        resolved_at = datetime.now(UTC)
        if run.booking_order_id is not None:
            self.db.execute(
                update(GHLSyncRun)
                .where(
                    GHLSyncRun.operator_id == self.operator_id,
                    GHLSyncRun.booking_order_id == run.booking_order_id,
                    GHLSyncRun.id != run.id,
                    GHLSyncRun.status.in_(("failed", "partial", "manual_review")),
                    GHLSyncRun.resolved_at.is_(None),
                )
                .values(resolved_at=resolved_at)
            )
        run.status = "succeeded"
        run.completed_at = resolved_at
        run.resolved_at = resolved_at
        run.last_error_code = None
        run.last_error = None
        run.last_http_status = None
        if run.booking_order_id is not None:
            order = self.db.get(BookingOrder, run.booking_order_id)
            if order is not None:
                order.ghl_contact_sync_status = "synced"
        self.db.commit()
        return GHLSyncResult(
            run_id=run.id,
            status=run.status,
            attempts=run.attempt_count,
            contact_id=contact_id,
            appointment_ids=tuple(appointment_ids),
        )

    def _failed(
        self,
        run: GHLSyncRun,
        *,
        status: str,
        contact_id: str | None,
        appointment_ids: list[str],
        error_code: str,
        error: str,
    ) -> GHLSyncResult:
        run.status = status
        run.completed_at = datetime.now(UTC)
        run.last_error_code = error_code
        run.last_error = error
        if run.booking_order_id is not None:
            order = self.db.get(BookingOrder, run.booking_order_id)
            if order is not None:
                order.ghl_contact_sync_status = "synced" if contact_id else "failed"
        self.db.commit()
        return GHLSyncResult(
            run_id=run.id,
            status=status,
            attempts=run.attempt_count,
            contact_id=contact_id,
            appointment_ids=tuple(appointment_ids),
            error_code=error_code,
            error=error,
        )

    def sync_order(
        self,
        order_id: uuid.UUID,
        *,
        trigger_type: str = "booking_created",
        requested_by_user_id: uuid.UUID | None = None,
    ) -> GHLSyncResult:
        order, bookings = self._order_bundle(order_id)
        run = self._new_run(order, trigger_type, requested_by_user_id)
        last_code = "ghl_sync_error"
        last_error = "HighLevel synchronization failed"
        contact_id: str | None = order.ghl_contact_id
        appointment_ids: list[str] = []

        for attempt_number in range(1, self.max_attempts + 1):
            run.attempt_count = attempt_number
            self.db.commit()
            appointment_ids = []
            try:
                contact_attempt = self._start_attempt(
                    run,
                    attempt_number=attempt_number,
                    entity_type="contact",
                    operation="upsert",
                )
                try:
                    contact_id = GHLContactService(self.db, self.operator_id).sync(order.id)
                except Exception as exc:
                    code, status, message = self._error_details(exc)
                    self._finish_attempt(
                        contact_attempt,
                        status="failed",
                        error_code=code,
                        error_message=message,
                        provider_http_status=status,
                    )
                    raise
                self._finish_attempt(contact_attempt, status="succeeded", remote_id=contact_id)

                for booking in bookings:
                    appointment_attempt = self._start_attempt(
                        run,
                        attempt_number=attempt_number,
                        entity_type="appointment",
                        operation="upsert",
                        booking_id=booking.id,
                    )
                    try:
                        remote_id = GHLAppointmentService(self.db, self.operator_id).sync(booking.id)
                    except Exception as exc:
                        code, status, message = self._error_details(exc)
                        self._finish_attempt(
                            appointment_attempt,
                            status="unknown" if "unknown" in message.lower() else "failed",
                            error_code=code,
                            error_message=message,
                            provider_http_status=status,
                        )
                        raise
                    if remote_id:
                        appointment_ids.append(str(remote_id))
                    self._finish_attempt(
                        appointment_attempt,
                        status="succeeded",
                        remote_id=str(remote_id) if remote_id else None,
                    )

                return self._succeed(run, contact_id, appointment_ids)
            except Exception as exc:
                last_code, last_error = self._set_run_error(run, exc)
                if attempt_number < self.max_attempts:
                    self.sleep(RETRY_DELAYS_SECONDS[min(attempt_number - 1, len(RETRY_DELAYS_SECONDS) - 1)])

        mapping_status = self.db.scalar(
            select(GHLAppointmentMapping.status)
            .where(
                GHLAppointmentMapping.operator_id == self.operator_id,
                GHLAppointmentMapping.booking_id.in_([booking.id for booking in bookings]),
                GHLAppointmentMapping.status == "manual_review",
            )
            .limit(1)
        )
        return self._failed(
            run,
            status="manual_review" if mapping_status else "failed",
            contact_id=contact_id,
            appointment_ids=appointment_ids,
            error_code=last_code,
            error=last_error,
        )
