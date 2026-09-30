from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import (
    Booking,
    BookingEvent,
    BookingOrder,
    BookingFinancialAllocation,
    OutboxJob,
    Payment,
)
from app.schemas.booking import BookingUpdate
from app.services.adjustment_service import AdjustmentService
from app.services.policy_service import PolicyService


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending_payment": {"confirmed", "cancelled", "failed"},
    "confirmed": {"completed", "no_show", "cancelled"},
    "completed": set(),
    "no_show": set(),
    "cancelled": set(),
    "failed": set(),
}


class BookingLifecycleService:
    """The only mutation path for booking status, cancellation, and rescheduling."""

    def __init__(self, db: Session, operator_id: uuid.UUID, settings: Settings | None = None) -> None:
        self.db = db
        self.operator_id = operator_id
        self.settings = settings

    def _settings(self) -> Settings:
        return self.settings or get_settings()

    def _booking_bundle(self, booking_id: uuid.UUID) -> tuple[Booking, BookingOrder, Payment]:
        booking = self.db.scalar(
            select(Booking)
            .where(Booking.id == booking_id, Booking.operator_id == self.operator_id)
            .with_for_update()
        )
        if booking is None:
            raise NotFoundError("Booking not found")
        order = self.db.scalar(
            select(BookingOrder).where(BookingOrder.id == booking.booking_order_id).with_for_update()
        )
        payment = self.db.scalar(
            select(Payment).where(Payment.booking_order_id == booking.booking_order_id).with_for_update()
        )
        if order is None or payment is None:
            raise NotFoundError("Booking payment not found")
        return booking, order, payment

    def _event(
        self,
        booking: Booking,
        *,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        actor_type: str,
        actor_id: uuid.UUID | None,
        reason: str | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.db.add(
            BookingEvent(
                operator_id=self.operator_id,
                booking_id=booking.id,
                order_id=booking.booking_order_id,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                actor_type=actor_type,
                actor_id=actor_id,
                reason=reason,
                payload=payload or {},
            )
        )

    def cancel(
        self,
        booking_id: uuid.UUID,
        *,
        reason: str = "booking_cancelled",
        actor_type: str = "operator",
        actor_id: uuid.UUID | None = None,
        force: bool = False,
        refund_mode: str | None = None,
        event_type: str = "cancelled",
        idempotency_key: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        booking, order, payment = self._booking_bundle(booking_id)
        if booking.status in {"cancelled", "failed"}:
            return {"booking_id": booking.id, "status": booking.status, "idempotent": True}
        policy = PolicyService(self.db).resolve_for_booking(booking)
        if not force and datetime.now(UTC) >= booking.start_at - timedelta(
            minutes=policy.cancellation_cutoff_minutes
        ):
            raise ConflictError("Cancellation is outside the booking policy cutoff")
        bookings = list(
            self.db.scalars(
                select(Booking)
                .where(Booking.booking_order_id == order.id)
                .order_by(Booking.id)
                .with_for_update()
            )
        )
        adjustments = AdjustmentService(self.db, self.operator_id)
        adjustments.ensure_financial_allocations(order, payment, bookings)
        key = idempotency_key or f"booking:{booking.id}:lifecycle-cancel"
        adjustment = adjustments.cancellation(
            booking,
            order,
            payment,
            policy,
            mode=refund_mode,
            reason=reason,
            idempotency_key=key,
        )
        allocation = self.db.scalar(
            select(BookingFinancialAllocation).where(
                BookingFinancialAllocation.booking_id == booking.id,
                BookingFinancialAllocation.payment_id == payment.id,
            )
        )
        if allocation is not None:
            adjustments.schedule_transfer_reversal(
                booking, order, payment, allocation, scope_key=key
            )
        previous = booking.status
        booking.status = "cancelled"
        booking.hold_expires_at = None
        remaining = self.db.scalar(
            select(Booking.id)
            .where(
                Booking.booking_order_id == order.id,
                Booking.id != booking.id,
                Booking.status.not_in(["cancelled", "failed"]),
            )
            .limit(1)
        )
        if remaining is None:
            order.status = "cancelled"
        self._event(
            booking,
            event_type=event_type,
            from_status=previous,
            to_status="cancelled",
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            payload={"adjustment_id": str(adjustment.id), **(payload or {})},
        )
        from app.services.public_access_service import PublicAccessService

        PublicAccessService(self.db).revoke(order_id=order.id, booking_id=booking.id)
        self.db.execute(
            insert(OutboxJob)
            .values(
                operator_id=self.operator_id,
                booking_order_id=order.id,
                job_type="ghl_cancel_appointment",
                idempotency_key=f"booking:{booking.id}:ghl_cancel",
                payload={"booking_id": str(booking.id), "booking_order_id": str(order.id)},
                status="pending",
            )
            .on_conflict_do_nothing(index_elements=[OutboxJob.idempotency_key])
        )
        self.db.commit()
        try:
            from app.services.outbox_service import OutboxService

            OutboxService(self.db, self._settings()).process(limit=100, prefer_newest=True)
        except Exception:
            # The durable outbox remains the retry path when provider calls fail.
            self.db.rollback()
        return {
            "booking_id": booking.id,
            "status": booking.status,
            "adjustment_id": adjustment.id,
            "adjustment_action": adjustment.action,
            "adjustment_amount_minor": adjustment.amount_minor,
            "idempotent": False,
        }

    def weather_cancel(
        self, booking_id: uuid.UUID, *, closure_id: uuid.UUID, mode: str, reason: str, actor_id: uuid.UUID | None
    ) -> dict[str, Any]:
        return self.cancel(
            booking_id,
            reason=reason,
            actor_type="operator",
            actor_id=actor_id,
            force=True,
            refund_mode=mode,
            event_type="weather_cancelled",
            idempotency_key=f"weather:{closure_id}:{booking_id}",
            payload={"refund_mode": mode, "closure_id": str(closure_id)},
        )

    def set_status(
        self,
        booking_id: uuid.UUID,
        status: str,
        *,
        reason: str,
        actor_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if status == "cancelled":
            return self.cancel(
                booking_id,
                reason=reason,
                actor_type="operator",
                actor_id=actor_id,
                force=True,
                idempotency_key=idempotency_key,
            )
        booking, order, payment = self._booking_bundle(booking_id)
        if status not in ALLOWED_TRANSITIONS.get(booking.status, set()):
            raise ConflictError(f"Cannot transition booking from {booking.status} to {status}")
        if status == "confirmed" and payment.status != "succeeded":
            raise ConflictError("A booking can only be confirmed after payment succeeds")
        adjustment = None
        if status == "no_show":
            policy = PolicyService(self.db).resolve_for_booking(booking)
            adjustments = AdjustmentService(self.db, self.operator_id)
            bookings = list(self.db.scalars(select(Booking).where(Booking.booking_order_id == order.id)))
            adjustments.ensure_financial_allocations(order, payment, bookings)
            adjustment = adjustments.no_show(
                booking, order, payment, policy,
                idempotency_key=idempotency_key or f"booking:{booking.id}:no-show",
            )
        previous = booking.status
        booking.status = status
        if status == "confirmed":
            order.status = "confirmed"
        self._event(
            booking,
            event_type="status_changed",
            from_status=previous,
            to_status=status,
            actor_type="operator",
            actor_id=actor_id,
            reason=reason,
            payload={"adjustment_id": str(adjustment.id)} if adjustment else {},
        )
        self.db.commit()
        return {"booking_id": booking.id, "status": status, "adjustment_id": adjustment.id if adjustment else None}

    def reschedule(
        self,
        booking_id: uuid.UUID,
        data: BookingUpdate,
        *,
        reason: str,
        actor_type: str = "operator",
        actor_id: uuid.UUID | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        booking, order, payment = self._booking_bundle(booking_id)
        policy = PolicyService(self.db).resolve_for_booking(booking)
        if not force and datetime.now(UTC) >= booking.start_at - timedelta(
            minutes=policy.reschedule_cutoff_minutes
        ):
            raise ConflictError("Rescheduling is outside the booking policy cutoff")
        if policy.reschedule_fee_minor:
            raise ConflictError("This policy requires an explicit reschedule fee collection")
        old_total = booking.line_total_minor or booking.base_price_minor * booking.units
        new_units = data.units or booking.units
        new_total = (old_total * new_units) // max(1, booking.units)
        delta = new_total - old_total
        if delta > 0:
            # Never move a paid booking while leaving an uncollected balance.
            raise ConflictError("Additional payment is required before this reschedule")
        from app.services.booking_admin_service import BookingAdminService

        result = BookingAdminService(self.db, self.operator_id).update(
            booking_id, data, allow_paid_reschedule=True
        )
        refreshed, order, payment = self._booking_bundle(booking_id)
        adjustment = None
        if delta < 0:
            adjustment = AdjustmentService(self.db, self.operator_id).reschedule_refund(
                refreshed,
                order,
                payment,
                amount_minor=-delta,
                original_amount_minor=old_total,
                policy_version=policy.version,
                idempotency_key=f"booking:{booking_id}:reschedule:{refreshed.start_at.isoformat()}:{refreshed.units}",
            )
        self._event(
            refreshed,
            event_type="rescheduled",
            from_status=refreshed.status,
            to_status=refreshed.status,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            payload={"old_total_minor": old_total, "new_total_minor": new_total, "delta_minor": delta},
        )
        self.db.commit()
        result["payment_outcome"] = "refund" if delta < 0 else "unchanged"
        result["adjustment_id"] = adjustment.id if adjustment else None
        return result
