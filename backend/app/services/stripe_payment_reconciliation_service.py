from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import BookingOrder, Payment, PaymentIntentRequest
from app.services.stripe_payment_service import StripePaymentService
from app.services.stripe_webhook_service import StripeWebhookService


class StripePaymentReconciliationService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def reconcile(self, payment_id: uuid.UUID) -> str:
        payment = self.db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
        if payment is None:
            raise RuntimeError("PaymentIntent reconciliation payment was not found")
        stripe = StripePaymentService(self.settings)
        if payment.stripe_payment_intent_id:
            intent = stripe.retrieve_payment_intent(payment.stripe_payment_intent_id)
        else:
            order = self.db.scalar(select(BookingOrder).where(BookingOrder.id == payment.booking_order_id))
            if order is None:
                raise RuntimeError("PaymentIntent reconciliation order was not found")
            candidate = stripe.find_payment_intent_for_order(str(order.id))
            if not candidate:
                raise RuntimeError("Stripe provider-unknown PaymentIntent was not found")
            metadata = candidate.get("metadata") or {}
            if metadata.get("booking_order_id") != str(order.id) or candidate.get("amount") != payment.customer_total_minor or candidate.get("currency") != payment.currency:
                raise RuntimeError("Stripe PaymentIntent metadata does not match the local payment")
            payment.stripe_payment_intent_id = candidate["id"]
            intent = candidate
            self.db.flush()
        data = intent.to_dict_recursive() if hasattr(intent, "to_dict_recursive") else dict(intent)
        status = str(data.get("status") or getattr(intent, "status", ""))
        event = {
            "id": f"reconcile:{payment.id}:{payment.stripe_payment_intent_id}:{status}",
            "type": "payment_intent.succeeded" if status == "succeeded" else "payment_intent.payment_failed",
            "data": {"object": data},
        }
        StripeWebhookService(self.db).process(event)
        request = self.db.scalar(
            select(PaymentIntentRequest).where(PaymentIntentRequest.payment_id == payment.id)
        )
        if request:
            request.status = "succeeded" if status == "succeeded" else "failed"
            self.db.commit()
        return status
