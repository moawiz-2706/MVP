from __future__ import annotations

import uuid

import stripe
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import BookingAdjustment


class StripeAdjustmentRefundService:
    def __init__(self, db: Session, settings: Settings) -> None:
        if not settings.stripe_secret_key:
            raise RuntimeError("STRIPE_SECRET_KEY is not configured")
        self.db = db
        self.settings = settings
        self.client = stripe.StripeClient(settings.stripe_secret_key, max_network_retries=2)

    def create_for_adjustment(self, adjustment_id: uuid.UUID) -> str:
        adjustment = self.db.scalar(
            select(BookingAdjustment).where(BookingAdjustment.id == adjustment_id).with_for_update()
        )
        if adjustment is None:
            raise RuntimeError("Adjustment refund was not found")
        metadata = adjustment.adjustment_metadata or {}
        if metadata.get("refund_id"):
            return str(metadata["refund_id"])
        if adjustment.status not in {"manual_review", "refund_pending"}:
            return "not-required"
        if not adjustment.stripe_reference:
            raise RuntimeError("Adjustment has no Stripe PaymentIntent to refund")
        adjustment.status = "refund_pending"
        self.db.commit()
        try:
            refund = self.client.v1.refunds.create(
                {
                    "payment_intent": adjustment.stripe_reference,
                    "amount": adjustment.amount_minor,
                    "metadata": {"booking_adjustment_id": str(adjustment.id)},
                },
                {"idempotency_key": f"booking_adjustment:{adjustment.id}:refund"},
            )
        except stripe.StripeError as exc:
            adjustment = self.db.get(BookingAdjustment, adjustment.id)
            if adjustment:
                adjustment.status = "manual_review"
                adjustment.adjustment_metadata = {
                    **(adjustment.adjustment_metadata or {}),
                    "refund_error": str(exc)[:2000],
                }
                self.db.commit()
            raise
        adjustment = self.db.get(BookingAdjustment, adjustment.id)
        if adjustment is None:
            raise RuntimeError("Adjustment disappeared during refund")
        refund_id = str(getattr(refund, "id", ""))
        adjustment.status = "refunded"
        adjustment.adjustment_metadata = {
            **(adjustment.adjustment_metadata or {}),
            "refund_id": refund_id,
        }
        self.db.commit()
        return refund_id
