from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import Booking, Payment, PaymentIntentRequest
from app.services.stripe_payment_service import StripePaymentService

# PaymentIntent states Stripe will not cancel because money has moved or is moving.
_NOT_CANCELLABLE = frozenset({"succeeded", "processing", "requires_capture"})


class AbandonedCheckoutService:
    """Close the Stripe side of a card checkout whose hold already expired.

    The local booking was released by hold expiry. Cancelling the PaymentIntent
    stops a stale checkout page from charging later. If Stripe reports the
    customer paid in the meantime, nothing is changed here: the verified
    payment_intent.succeeded webhook finds the cancelled booking and refunds it.
    """

    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def cancel_intent(self, payment_id: uuid.UUID) -> str:
        payment = self.db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
        if payment is None:
            raise RuntimeError("Abandoned checkout payment was not found")
        if payment.status != "processing" or not payment.stripe_payment_intent_id:
            return "skipped"
        active = self.db.scalar(
            select(Booking.id).where(
                Booking.booking_order_id == payment.booking_order_id,
                Booking.status.in_(("pending_payment", "confirmed")),
            )
        )
        if active is not None:
            # The order was confirmed or re-held after the job was queued.
            return "skipped"
        stripe = StripePaymentService(self.settings)
        intent_id = payment.stripe_payment_intent_id
        intent = stripe.retrieve_payment_intent(intent_id)
        if intent.status in _NOT_CANCELLABLE:
            self.db.commit()
            return intent.status
        if intent.status != "canceled":
            intent = stripe.cancel_payment_intent(intent_id, idempotency_key=f"payment:{payment.id}:abandoned-cancel")
        if intent.status != "canceled":
            raise RuntimeError(f"PaymentIntent cancellation left status {intent.status}")
        payment.status = "failed"
        request_row = self.db.scalar(
            select(PaymentIntentRequest).where(PaymentIntentRequest.payment_id == payment.id)
        )
        if request_row is not None and request_row.status in ("pending", "processing"):
            request_row.status = "failed"
            request_row.last_error = "Checkout abandoned; hold expired"
        self.db.commit()
        return "canceled"
