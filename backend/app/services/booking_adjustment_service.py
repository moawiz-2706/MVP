from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import (
    Booking,
    BookingAdjustment,
    BookingEvent,
    BookingOrder,
    OutboxJob,
    Payment,
    PaymentRefundAttempt,
)
from app.schemas.booking import BookingUpdate
from app.services.adjustment_service import AdjustmentService
from app.services.booking_admin_service import BookingAdminService
from app.services.policy_service import PolicyService
from app.services.stripe_payment_service import StripePaymentService


class BookingAdjustmentService:
    """Coordinates money-safe booking changes outside the ordinary PATCH path."""

    def __init__(self, db: Session, operator_id: uuid.UUID, settings: Settings | None = None) -> None:
        self.db = db
        self.operator_id = operator_id
        self.settings = settings or get_settings()

    def _locked_bundle(self, booking_id: uuid.UUID) -> tuple[Booking, BookingOrder, Payment]:
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

    @staticmethod
    def _total(booking: Booking, units: int) -> int:
        old_total = booking.line_total_minor or booking.base_price_minor * booking.units
        return (old_total * units) // max(1, booking.units)

    def _response(
        self,
        adjustment: BookingAdjustment,
        *,
        booking: dict[str, Any] | None = None,
        client_secret: str | None = None,
    ) -> dict[str, Any]:
        return {
            "adjustment_id": adjustment.id,
            "status": adjustment.status,
            "action": adjustment.action,
            "amount_minor": adjustment.amount_minor,
            "currency": adjustment.currency,
            "stripe_payment_intent_id": adjustment.stripe_reference,
            "client_secret": client_secret,
            "booking": booking,
        }

    def _existing_response(self, adjustment: BookingAdjustment) -> dict[str, Any]:
        client_secret = None
        if adjustment.action == "charge" and adjustment.stripe_reference and adjustment.status in {
            "processing",
            "pending",
        }:
            intent = StripePaymentService(self.settings).retrieve_payment_intent(adjustment.stripe_reference)
            client_secret = getattr(intent, "client_secret", None)
        return self._response(adjustment, client_secret=client_secret)

    def create(
        self,
        booking_id: uuid.UUID,
        data: BookingUpdate,
        *,
        actor_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        booking, order, payment = self._locked_bundle(booking_id)
        if booking.status not in {"pending_payment", "confirmed"}:
            raise ConflictError("Only pending or confirmed bookings can be adjusted")
        key = idempotency_key or f"booking:{booking.id}:adjust:{data.start_at.isoformat() if data.start_at else ''}:{data.units or booking.units}"
        existing = self.db.scalar(
            select(BookingAdjustment).where(
                BookingAdjustment.operator_id == self.operator_id,
                BookingAdjustment.idempotency_key == key,
            )
        )
        if existing is not None:
            return self._existing_response(existing)

        target_start = data.start_at or booking.start_at
        target_units = data.units or booking.units
        old_total = booking.line_total_minor or booking.base_price_minor * booking.units
        new_total = self._total(booking, target_units)
        delta = new_total - old_total
        policy = PolicyService(self.db).resolve_for_booking(booking)
        metadata = {
            "target_start_at": target_start.isoformat(),
            "target_units": target_units,
            "old_start_at": booking.start_at.isoformat(),
            "old_units": booking.units,
            "old_total_minor": old_total,
            "new_total_minor": new_total,
            "actor_id": str(actor_id) if actor_id else None,
        }

        if delta > 0:
            adjustment = BookingAdjustment(
                operator_id=self.operator_id,
                booking_id=booking.id,
                payment_id=payment.id,
                action="charge",
                amount_minor=delta,
                original_amount_minor=old_total,
                currency=payment.currency,
                reason="paid_booking_increase",
                policy_version=policy.version,
                idempotency_key=key,
                status="pending",
                adjustment_metadata=metadata,
            )
            self.db.add(adjustment)
            self.db.flush()
            try:
                intent_id, client_secret = StripePaymentService(self.settings).create_payment_intent(
                    order_id=str(order.id),
                    operator_id=str(self.operator_id),
                    public_reference=order.public_reference,
                    amount_minor=delta,
                    currency=payment.currency,
                    receipt_email=order.customer_email,
                    idempotency_key=f"booking_adjustment:{adjustment.id}",
                    metadata_extra={
                        "booking_adjustment_id": str(adjustment.id),
                        "booking_id": str(booking.id),
                        "adjustment_amount_minor": str(delta),
                    },
                )
            except Exception:
                self.db.rollback()
                raise ConflictError("Stripe could not start the additional payment. The booking was not changed.")
            adjustment.stripe_reference = intent_id
            adjustment.status = "processing"
            self.db.commit()
            return self._response(adjustment, client_secret=client_secret)

        # A decrease or a same-price time change can be applied immediately.
        result = BookingAdminService(self.db, self.operator_id).update(
            booking.id,
            BookingUpdate(start_at=target_start, units=target_units),
            allow_paid_reschedule=True,
        )
        self.db.expire_all()
        booking, order, payment = self._locked_bundle(booking_id)
        if delta < 0 and payment.status == "succeeded":
            adjustments = AdjustmentService(self.db, self.operator_id)
            all_bookings = list(
                self.db.scalars(select(Booking).where(Booking.booking_order_id == order.id))
            )
            adjustments.ensure_financial_allocations(order, payment, all_bookings)
            adjustment = adjustments.reschedule_refund(
                booking,
                order,
                payment,
                amount_minor=-delta,
                original_amount_minor=old_total,
                policy_version=policy.version,
                idempotency_key=key,
                metadata=metadata,
            )
            attempt_id = self.db.scalar(
                select(PaymentRefundAttempt.id).where(
                    PaymentRefundAttempt.payment_id == payment.id,
                    PaymentRefundAttempt.scope_key == f"adjustment:{booking.id}:{key}",
                )
            )
            if attempt_id is not None:
                # Vercel/serverless deployments may not have a continuously
                # running worker. Try the refund during the request, while
                # retaining the outbox row as an idempotent retry fallback.
                try:
                    from app.services.stripe_refund_service import StripeRefundService

                    StripeRefundService(self.db, self.settings).create_for_attempt(attempt_id)
                except Exception:
                    pass
        else:
            adjustment = BookingAdjustment(
                operator_id=self.operator_id,
                booking_id=booking.id,
                payment_id=payment.id,
                action="none",
                amount_minor=0,
                original_amount_minor=old_total,
                currency=payment.currency,
                reason="paid_booking_time_change" if delta == 0 else "unpaid_booking_decrease",
                policy_version=policy.version,
                idempotency_key=key,
                status="completed",
                adjustment_metadata=metadata,
            )
            self.db.add(adjustment)
        self.db.add(
            BookingEvent(
                operator_id=self.operator_id,
                booking_id=booking.id,
                order_id=order.id,
                event_type="booking_adjusted",
                from_status=booking.status,
                to_status=booking.status,
                actor_type="operator",
                actor_id=actor_id,
                reason=adjustment.reason,
                payload={"adjustment_id": str(adjustment.id), **metadata},
            )
        )
        self.db.commit()
        return self._response(adjustment, booking=BookingAdminService(self.db, self.operator_id).detail(booking.id))

    def apply_paid_increase(self, adjustment_id: uuid.UUID, intent: dict[str, Any]) -> None:
        adjustment = self.db.scalar(
            select(BookingAdjustment)
            .where(
                BookingAdjustment.id == adjustment_id,
                BookingAdjustment.operator_id == self.operator_id,
            )
            .with_for_update()
        )
        if adjustment is None:
            raise NotFoundError("Booking adjustment not found")
        if adjustment.status == "succeeded":
            return
        if adjustment.action != "charge":
            raise ConflictError("The Stripe PaymentIntent is not an adjustment charge")
        if int(intent.get("amount") or 0) != adjustment.amount_minor:
            raise ConflictError("Adjustment payment amount does not match the requested change")
        if str(intent.get("currency") or "").lower() != adjustment.currency.lower():
            raise ConflictError("Adjustment payment currency does not match the booking")
        if str(intent.get("status")) != "succeeded":
            raise ConflictError("Adjustment PaymentIntent is not successful")
        metadata = intent.get("metadata") or {}
        if metadata.get("booking_adjustment_id") != str(adjustment.id):
            raise ConflictError("Adjustment PaymentIntent metadata does not match the booking")
        booking_id = adjustment.booking_id
        target = adjustment.adjustment_metadata or {}
        target_start = datetime.fromisoformat(str(target["target_start_at"]))
        target_units = int(target["target_units"])
        try:
            result = BookingAdminService(self.db, self.operator_id).update(
                booking_id,
                BookingUpdate(start_at=target_start, units=target_units),
                allow_paid_reschedule=True,
            )
        except Exception as exc:
            adjustment.status = "manual_review"
            adjustment.adjustment_metadata = {
                **target,
                "provider_charge_id": self._charge_id(intent),
                "apply_error": str(exc)[:1000],
                "refund_required": True,
            }
            self.db.execute(
                insert(OutboxJob)
                .values(
                    operator_id=self.operator_id,
                    booking_order_id=booking_id and self.db.scalar(
                        select(Booking.booking_order_id).where(Booking.id == booking_id)
                    ),
                    job_type="stripe_create_adjustment_refund",
                    idempotency_key=f"booking_adjustment:{adjustment.id}:refund",
                    payload={"adjustment_id": str(adjustment.id)},
                    status="pending",
                )
                .on_conflict_do_nothing(index_elements=[OutboxJob.idempotency_key])
            )
            self.db.commit()
            raise
        adjustment.status = "succeeded"
        adjustment.stripe_reference = str(intent.get("id") or adjustment.stripe_reference or "")
        adjustment.adjustment_metadata = {**target, "provider_charge_id": self._charge_id(intent)}
        booking = self.db.get(Booking, booking_id)
        if booking is not None:
            self.db.add(
                BookingEvent(
                    operator_id=self.operator_id,
                    booking_id=booking.id,
                    order_id=booking.booking_order_id,
                    event_type="booking_adjusted",
                    from_status=booking.status,
                    to_status=booking.status,
                    actor_type="stripe",
                    actor_id=None,
                    reason="paid_booking_increase",
                    payload={"adjustment_id": str(adjustment.id), "amount_minor": adjustment.amount_minor},
                )
            )
        self.db.commit()

    @staticmethod
    def _charge_id(intent: dict[str, Any]) -> str | None:
        charge = intent.get("latest_charge")
        if isinstance(charge, dict):
            return str(charge.get("id") or "") or None
        return str(charge) if charge else None
