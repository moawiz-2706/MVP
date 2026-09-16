from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import Payment, PaymentIntentRequest
from app.services.stripe_payment_service import StripePaymentService
from app.services.stripe_webhook_service import StripeWebhookService


class StripePaymentReconciliationService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def reconcile(self, payment_id: uuid.UUID) -> str:
        payment = self.db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
        if payment is None or not payment.stripe_payment_intent_id:
            raise RuntimeError("PaymentIntent reconciliation has no provider ID")
        intent = StripePaymentService(self.settings).retrieve_payment_intent(
            payment.stripe_payment_intent_id
        )
        data = intent.to_dict_recursive() if hasattr(intent, "to_dict_recursive") else dict(intent)
        status = str(data.get("status") or getattr(intent, "status", ""))
        event = {
            "id": f"reconcile:{payment.id}:{payment.stripe_payment_intent_id}",
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
