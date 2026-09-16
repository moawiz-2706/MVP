from __future__ import annotations

import uuid

import stripe
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import Payment, PaymentRefundAttempt


class StripeRefundService:
    def __init__(self, db: Session, settings: Settings) -> None:
        if not settings.stripe_secret_key:
            raise RuntimeError("STRIPE_SECRET_KEY is not configured")
        self.db = db
        self.settings = settings
        self.client = stripe.StripeClient(settings.stripe_secret_key, max_network_retries=2)

    def create_for_attempt(self, attempt_id: uuid.UUID) -> str:
        attempt = self.db.scalar(
            select(PaymentRefundAttempt).where(PaymentRefundAttempt.id == attempt_id).with_for_update()
        )
        if attempt is None:
            raise RuntimeError("Refund attempt not found")
        if attempt.status == "succeeded" and attempt.stripe_refund_id:
            return attempt.stripe_refund_id
        payment = self.db.scalar(select(Payment).where(Payment.id == attempt.payment_id).with_for_update())
        if payment is None:
            raise RuntimeError("Refund payment not found")
        if attempt.amount_minor <= 0:
            attempt.status = "succeeded"
            self.db.commit()
            return "zero-refund"
        if not payment.stripe_payment_intent_id and not payment.stripe_charge_id:
            raise RuntimeError("Refund payment has no Stripe PaymentIntent or charge")
        params: dict[str, object] = {"amount": attempt.amount_minor, "metadata": {"refund_scope": attempt.scope_key}}
        if payment.stripe_payment_intent_id:
            params["payment_intent"] = payment.stripe_payment_intent_id
        else:
            params["charge"] = payment.stripe_charge_id
        attempt.status = "pending"
        self.db.commit()
        try:
            refund = self.client.v1.refunds.create(
                params,
                {"idempotency_key": attempt.idempotency_key},
            )
        except stripe.StripeError as exc:
            attempt = self.db.get(PaymentRefundAttempt, attempt_id)
            if attempt:
                attempt.status = "failed"
                attempt.failure_reason = str(exc)[:2000]
                self.db.commit()
            raise
        status = str(getattr(refund, "status", "pending"))
        attempt = self.db.get(PaymentRefundAttempt, attempt_id)
        if attempt is None:
            raise RuntimeError("Refund attempt disappeared")
        attempt.stripe_refund_id = str(getattr(refund, "id", "")) or None
        attempt.status = "succeeded" if status == "succeeded" else status
        if attempt.status not in {"pending", "succeeded", "failed", "canceled", "requires_action"}:
            attempt.status = "pending"
        self.db.commit()
        return attempt.stripe_refund_id or "pending"
