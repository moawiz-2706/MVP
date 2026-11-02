from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Booking, BookingEvent, BookingOrder, OutboxJob, Payment
from app.services.public_access_service import PublicAccessService


# A card checkout may still be finishing (3-D Secure, slow bank) just after its
# hold lapses. Its hold no longer reserves inventory, but the booking is only
# released and the PaymentIntent cancelled once this grace has also passed.
ABANDONED_CARD_GRACE = timedelta(minutes=30)
PAID_PAYMENT_STATUSES = frozenset({"succeeded", "partially_refunded", "refunded"})
PAID_ORDER_STATUSES = frozenset({"confirmed", "partially_refunded", "refunded"})


class ReservationLifecycleService:
    """Owns local reservation transitions that must run even without a browser."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def expire_pending_holds(self, *, now: datetime | None = None, limit: int = 250) -> dict[str, int]:
        now = now or datetime.now(UTC)
        expired = cancelled = skipped_paid = 0
        rows = self.db.execute(
            select(Booking, BookingOrder, Payment)
            .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
            .join(Payment, Payment.booking_order_id == BookingOrder.id)
            .where(
                Booking.status == "pending_payment",
                Booking.hold_expires_at.is_not(None),
                Booking.hold_expires_at <= now,
            )
            .order_by(Booking.hold_expires_at, Booking.id)
            .limit(limit)
            .with_for_update(of=(Booking, BookingOrder, Payment), skip_locked=True)
        ).all()
        for booking, order, payment in rows:
            if payment.status in PAID_PAYMENT_STATUSES or order.status in PAID_ORDER_STATUSES:
                skipped_paid += 1
                continue
            awaiting_card = payment.status == "processing"
            if awaiting_card and booking.hold_expires_at > now - ABANDONED_CARD_GRACE:
                skipped_paid += 1
                continue
            before = booking.status
            booking.status = "cancelled"
            booking.updated_at = now
            self.db.add(
                BookingEvent(
                    operator_id=booking.operator_id,
                    booking_id=booking.id,
                    order_id=order.id,
                    event_type="hold_expired",
                    from_status=before,
                    to_status="cancelled",
                    actor_type="system",
                    reason="Payment hold expired before confirmation",
                    occurred_at=now,
                )
            )
            self.db.add(
                OutboxJob(
                    operator_id=booking.operator_id,
                    booking_order_id=order.id,
                    job_type="ghl_cancel_appointment",
                    idempotency_key=f"booking:{booking.id}:ghl_expired_cancel",
                    payload={"booking_id": str(booking.id), "booking_order_id": str(order.id), "reason": "hold_expired"},
                    status="pending",
                )
            )
            remaining = self.db.scalar(
                select(Booking.id).where(
                    Booking.booking_order_id == order.id,
                    Booking.id != booking.id,
                    Booking.status.in_(["pending_payment", "confirmed"]),
                )
            )
            if remaining is None:
                order.status = "expired"
                PublicAccessService(self.db).revoke(order_id=order.id)
                if awaiting_card and payment.stripe_payment_intent_id:
                    self.db.add(
                        OutboxJob(
                            operator_id=booking.operator_id,
                            booking_order_id=order.id,
                            job_type="stripe_cancel_payment_intent",
                            idempotency_key=f"payment:{payment.id}:abandoned-cancel",
                            payload={"payment_id": str(payment.id)},
                            status="pending",
                        )
                    )
            expired += 1
            cancelled += 1
        self.db.commit()
        return {"expired_holds": expired, "cancelled_bookings": cancelled, "skipped_paid": skipped_paid}
