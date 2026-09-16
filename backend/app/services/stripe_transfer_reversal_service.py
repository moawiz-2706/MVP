from __future__ import annotations

import uuid

import stripe
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import StripeTransfer, TransferReversalAttempt


class StripeTransferReversalService:
    def __init__(self, db: Session, settings: Settings) -> None:
        if not settings.stripe_secret_key:
            raise RuntimeError("STRIPE_SECRET_KEY is not configured")
        self.db = db
        self.client = stripe.StripeClient(settings.stripe_secret_key, max_network_retries=2)

    def create_for_attempt(self, attempt_id: uuid.UUID) -> str:
        attempt = self.db.scalar(
            select(TransferReversalAttempt).where(
                TransferReversalAttempt.id == attempt_id
            ).with_for_update()
        )
        if attempt is None:
            raise RuntimeError("Transfer reversal attempt not found")
        if attempt.status == "succeeded" and attempt.stripe_reversal_id:
            return attempt.stripe_reversal_id
        transfer = self.db.scalar(
            select(StripeTransfer).where(StripeTransfer.id == attempt.transfer_id).with_for_update()
        )
        if transfer is None:
            raise RuntimeError("Stripe transfer not found")
        if not transfer.stripe_transfer_id:
            attempt.status = "not_transferred"
            self.db.commit()
            return "not-transferred"
        available = max(0, transfer.amount_minor - transfer.reversed_minor)
        amount = min(attempt.amount_minor, available)
        if amount <= 0:
            attempt.status = "succeeded"
            self.db.commit()
            return "already-reversed"
        attempt.status = "pending"
        self.db.commit()
        try:
            reversal = self.client.v1.transfers.reversals.create(
                transfer.stripe_transfer_id,
                {"amount": amount, "metadata": {"reversal_scope": attempt.scope_key}},
                {"idempotency_key": attempt.idempotency_key},
            )
        except stripe.StripeError as exc:
            attempt = self.db.get(TransferReversalAttempt, attempt_id)
            if attempt:
                attempt.status = "failed"
                attempt.failure_reason = str(exc)[:2000]
                self.db.commit()
            raise
        attempt = self.db.get(TransferReversalAttempt, attempt_id)
        transfer = self.db.get(StripeTransfer, transfer.id)
        if attempt is None or transfer is None:
            raise RuntimeError("Transfer reversal state disappeared")
        reversal_id = str(getattr(reversal, "id", "")) or None
        attempt.stripe_reversal_id = reversal_id
        transfer.reversed_minor = min(transfer.amount_minor, transfer.reversed_minor + amount)
        transfer.status = "reversed" if transfer.reversed_minor >= transfer.amount_minor else "partially_reversed"
        attempt.status = "succeeded"
        self.db.commit()
        return reversal_id or "reversed"
