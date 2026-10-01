from __future__ import annotations

import uuid

import stripe
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import BookingOrder, Operator, Payment


class StripeInvoiceService:
    """Create and send hosted invoices for authenticated team bookings.

    Card data never enters Passport. Stripe owns the customer payment page and
    sends invoice lifecycle webhooks back to Passport.
    """

    def __init__(self, db: Session, settings: Settings) -> None:
        if not settings.stripe_secret_key:
            raise RuntimeError("STRIPE_SECRET_KEY is not configured")
        self.db = db
        self.client = stripe.StripeClient(settings.stripe_secret_key, max_network_retries=2)

    @staticmethod
    def _value(obj, key: str, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def _find_existing_invoice(self, order: BookingOrder):
        result = self.client.v1.invoices.search(
            {
                "query": f"metadata['booking_order_id']:'{order.id}'",
                "limit": 10,
            }
        )
        data = result.to_dict_recursive() if hasattr(result, "to_dict_recursive") else dict(result)
        invoices = data.get("data", [])
        return invoices[0] if invoices else None

    def create_for_payment(self, payment_id: uuid.UUID) -> str | None:
        row = self.db.execute(
            select(Payment, BookingOrder, Operator)
            .join(BookingOrder, BookingOrder.id == Payment.booking_order_id)
            .join(Operator, Operator.id == BookingOrder.operator_id)
            .where(Payment.id == payment_id)
            .with_for_update()
        ).one_or_none()
        if row is None:
            raise RuntimeError("Invoice payment record not found")
        payment, order, operator = row
        # Do not hold the only pooled database connection while making Stripe
        # network calls. Each persistence step below commits before the next
        # provider call and therefore returns the connection to the pool.
        self.db.commit()
        if payment.payment_method != "invoice":
            return None
        if payment.status == "succeeded":
            return payment.stripe_invoice_url

        if not payment.stripe_customer_id:
            customer = self.client.v1.customers.create(
                {
                    "email": order.customer_email,
                    "name": f"{order.customer_first_name} {order.customer_last_name}".strip(),
                    "phone": order.customer_phone,
                    "metadata": {
                        "operator_id": str(order.operator_id),
                        "booking_order_id": str(order.id),
                    },
                },
                {"idempotency_key": f"booking:{order.id}:stripe_customer"},
            )
            payment.stripe_customer_id = self._value(customer, "id")
            if not payment.stripe_customer_id:
                raise RuntimeError("Stripe did not return a customer ID")
            self.db.commit()

        if not payment.stripe_invoice_item_id:
            item = self.client.v1.invoice_items.create(
                {
                    "customer": payment.stripe_customer_id,
                    "amount": payment.customer_total_minor,
                    "currency": payment.currency,
                    "description": f"Passport booking {order.public_reference} — {operator.name}",
                    "metadata": {
                        "booking_order_id": str(order.id),
                        "operator_id": str(order.operator_id),
                        "public_reference": order.public_reference,
                    },
                },
                {"idempotency_key": f"booking:{order.id}:stripe_invoice_item"},
            )
            payment.stripe_invoice_item_id = self._value(item, "id")
            if not payment.stripe_invoice_item_id:
                raise RuntimeError("Stripe did not return an invoice item ID")
            self.db.commit()

        invoice = None
        if payment.stripe_invoice_id:
            invoice = self.client.v1.invoices.retrieve(payment.stripe_invoice_id)
        else:
            invoice = self._find_existing_invoice(order)
            if invoice is None:
                invoice = self.client.v1.invoices.create(
                    {
                        "customer": payment.stripe_customer_id,
                        "collection_method": "send_invoice",
                        "days_until_due": 7,
                        "auto_advance": True,
                        "metadata": {
                            "booking_order_id": str(order.id),
                            "operator_id": str(order.operator_id),
                            "public_reference": order.public_reference,
                        },
                    },
                    {"idempotency_key": f"booking:{order.id}:stripe_invoice"},
                )
            payment.stripe_invoice_id = self._value(invoice, "id")
            if not payment.stripe_invoice_id:
                raise RuntimeError("Stripe did not return an invoice ID")
            self.db.commit()

        status = self._value(invoice, "status") or "draft"
        if status == "draft":
            invoice = self.client.v1.invoices.finalize_invoice(payment.stripe_invoice_id)
            status = self._value(invoice, "status") or "open"
        if status == "open":
            invoice = self.client.v1.invoices.send_invoice(payment.stripe_invoice_id)
            status = self._value(invoice, "status") or "open"

        payment.invoice_status = status
        payment.stripe_invoice_url = self._value(invoice, "hosted_invoice_url")
        if status != "open" or not payment.stripe_invoice_url:
            raise RuntimeError("Stripe invoice was not finalized and sent to the customer")
        self.db.commit()
        return payment.stripe_invoice_url
