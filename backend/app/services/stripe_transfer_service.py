import uuid

import stripe
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import BookingOrder, Payment, StripeConnection, StripeTransfer


class StripeTransferService:
    def __init__(self, db: Session, settings: Settings) -> None:
        if not settings.stripe_secret_key:
            raise RuntimeError("STRIPE_SECRET_KEY is not configured")
        self.db = db
        self.client = stripe.StripeClient(settings.stripe_secret_key, max_network_retries=2)

    def create_for_order(self, order_id: uuid.UUID) -> str:
        row = self.db.execute(
            select(Payment, BookingOrder, StripeConnection)
            .join(BookingOrder, BookingOrder.id == Payment.booking_order_id)
            .join(StripeConnection, StripeConnection.operator_id == Payment.operator_id)
            .where(BookingOrder.id == order_id)
        ).one_or_none()
        if row is None:
            raise RuntimeError("Transfer prerequisites are missing")
        payment, order, connection = row
        if payment.status != "succeeded":
            raise RuntimeError("Payment has not succeeded")
        if not payment.stripe_charge_id or not payment.stripe_charge_id.startswith("ch_"):
            raise RuntimeError("Transfer source_transaction must be a successful Charge ID")
        transfer = self.db.scalar(
            select(StripeTransfer).where(StripeTransfer.payment_id == payment.id)
        )
        if transfer and transfer.status == "created" and transfer.stripe_transfer_id:
            return transfer.stripe_transfer_id
        if transfer is None:
            transfer = StripeTransfer(
                operator_id=payment.operator_id,
                payment_id=payment.id,
                stripe_connected_account_id=connection.stripe_account_id,
                stripe_source_transaction_id=payment.stripe_charge_id,
                transfer_group=f"booking_order_{order.public_reference}",
                amount_minor=payment.operator_transfer_minor,
                currency=payment.currency,
                status="pending",
            )
            self.db.add(transfer)
            self.db.commit()
        try:
            created = self.client.v1.transfers.create(
                {
                    "amount": transfer.amount_minor,
                    "currency": transfer.currency,
                    "destination": transfer.stripe_connected_account_id,
                    "source_transaction": transfer.stripe_source_transaction_id,
                    "transfer_group": transfer.transfer_group,
                    "metadata": {
                        "booking_order_id": str(order.id),
                        "payment_id": str(payment.id),
                    },
                },
                {"idempotency_key": f"booking_order:{order.id}:operator_transfer"},
            )
        except Exception as exc:
            transfer.status = "failed"
            transfer.last_error = str(exc)[:2000]
            self.db.commit()
            raise
        transfer.stripe_transfer_id = created.id
        transfer.status = "created"
        transfer.last_error = None
        self.db.commit()
        return created.id

