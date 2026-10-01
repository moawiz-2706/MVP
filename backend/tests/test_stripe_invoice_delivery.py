import os
import uuid

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models.entities import BookingOrder, Operator, Payment, StripeConnection, StripeTransfer
from app.services.stripe_invoice_service import StripeInvoiceService
from app.services.stripe_transfer_service import StripeTransferService

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database",
)


class _FakeCustomers:
    def create(self, _payload, _options):
        return {"id": "cus_invoice_test"}


class _FakeInvoiceItems:
    def create(self, _payload, _options):
        return {"id": "ii_invoice_test"}


class _FakeInvoices:
    def __init__(self):
        self.state = {
            "id": "in_invoice_test",
            "status": "draft",
            "hosted_invoice_url": None,
        }
        self.send_calls = 0

    def search(self, _params):
        return {"data": []}

    def create(self, _payload, _options):
        return dict(self.state)

    def finalize_invoice(self, _invoice_id):
        self.state["status"] = "open"
        return {"id": self.state["id"], "status": "open"}

    def send_invoice(self, _invoice_id):
        self.send_calls += 1
        self.state["status"] = "open"
        self.state["hosted_invoice_url"] = "https://invoice.stripe.test/in_invoice_test"
        # Simulate a provider response that omits the URL even though the send
        # was accepted; the service must re-fetch the canonical invoice.
        return {"id": self.state["id"], "status": "open"}

    def retrieve(self, _invoice_id):
        return dict(self.state)


class _FakeV1:
    def __init__(self):
        self.customers = _FakeCustomers()
        self.invoice_items = _FakeInvoiceItems()
        self.invoices = _FakeInvoices()


class _FakeStripeClient:
    def __init__(self):
        self.v1 = _FakeV1()


def _order_payment(db, *, order_status="pending_payment"):
    operator = Operator(
        ghl_location_id=f"loc-{uuid.uuid4().hex}",
        name="Invoice Test Operator",
        slug=f"invoice-{uuid.uuid4().hex[:8]}",
        time_zone="UTC",
    )
    db.add(operator)
    db.flush()
    order = BookingOrder(
        operator_id=operator.id,
        public_reference=f"INV-{uuid.uuid4().hex[:10]}",
        customer_first_name="Invoice",
        customer_last_name="Client",
        customer_email="invoice@example.com",
        currency="usd",
        subtotal_minor=5000,
        platform_fee_and_taxes_minor=0,
        customer_total_minor=5000,
        operator_transfer_minor=0,
        platform_gross_retained_minor=0,
        status=order_status,
    )
    db.add(order)
    db.flush()
    payment = Payment(
        operator_id=operator.id,
        booking_order_id=order.id,
        currency="usd",
        subtotal_minor=5000,
        platform_fee_and_taxes_minor=0,
        customer_total_minor=5000,
        operator_transfer_minor=0,
        platform_gross_retained_minor=0,
        payment_method="invoice",
        status="requires_payment",
    )
    db.add(payment)
    db.flush()
    return operator, order, payment


def test_invoice_send_reloads_canonical_hosted_url(db):
    _operator, _order, payment = _order_payment(db)
    db.commit()

    service = StripeInvoiceService(db, Settings(stripe_secret_key="sk_test_invoice"))
    fake = _FakeStripeClient()
    service.client = fake

    result = service.create_for_payment(payment.id)

    db.refresh(payment)
    assert result == "https://invoice.stripe.test/in_invoice_test"
    assert payment.invoice_status == "open"
    assert payment.stripe_invoice_url == result
    assert fake.v1.invoices.send_calls == 1


def test_cancelled_transfer_job_is_a_completed_noop(db):
    operator, order, payment = _order_payment(db, order_status="exception")
    payment.status = "succeeded"
    payment.stripe_charge_id = "ch_late_payment"
    db.add(
        StripeConnection(
            operator_id=operator.id,
            stripe_account_id="acct_test_invoice",
            onboarding_complete=True,
            payouts_enabled=True,
            transfers_capability_status="active",
        )
    )
    db.commit()

    result = StripeTransferService(db, Settings(stripe_secret_key="sk_test_transfer")).create_for_order(order.id)

    assert result is None
    assert db.scalar(select(StripeTransfer).where(StripeTransfer.payment_id == payment.id)) is None
