import os
import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models.entities import Booking, BookingOrder, Calendar, CalendarHour, CalendarRate, Operator, OutboxJob, Payment, StripeConnection
from app.schemas.order import OrderCreateRequest, OrderCustomer, OrderItemRequest
from app.services.order_service import OrderService
from app.services.stripe_webhook_service import StripeWebhookService

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run invoice booking tests",
)


def _operator_calendar(db):
    operator = Operator(
        ghl_location_id=f"loc-{uuid.uuid4().hex}",
        name="Invoice Test Operator",
        slug=f"invoice-{uuid.uuid4().hex[:8]}",
        time_zone="America/New_York",
    )
    db.add(operator)
    db.flush()
    calendar = Calendar(
        operator_id=operator.id,
        name="Invoice Tour",
        slug=f"tour-{uuid.uuid4().hex[:8]}",
        duration_minutes=60,
        slot_interval_minutes=30,
        base_price_minor=5000,
    )
    db.add(calendar)
    db.flush()
    return operator, calendar


def test_payment_mode_requires_explicit_team_authorization():
    assert OrderService.payment_mode(5000, None, allow_override=False) == (True, False, True, "card")
    assert OrderService.payment_mode(5000, True, allow_override=True) == (True, True, False, "invoice")
    assert OrderService.payment_mode(5000, False, allow_override=True) == (False, False, False, "none")
    # A public request cannot smuggle in payment_required=false to bypass payment.
    assert OrderService.payment_mode(5000, False, allow_override=False) == (True, False, True, "card")
    assert OrderService.payment_mode(0, True, allow_override=True) == (False, False, False, "none")


def test_authenticated_free_booking_skips_invoice_and_confirms_immediately(db):
    operator, calendar = _operator_calendar(db)
    operator.public_booking_enabled = True
    calendar.public_booking_enabled = True
    db.add_all(
        [
            CalendarHour(calendar_id=calendar.id, day_of_week=day, start_time=time(0), end_time=time(23, 59))
            for day in range(7)
        ]
    )
    db.commit()
    request = OrderCreateRequest(
        items=[OrderItemRequest(calendar_id=calendar.id, start_at=datetime(2027, 1, 4, 14, tzinfo=UTC), units=1)],
        customer=OrderCustomer(first_name="Free", last_name="Client", email="free@example.com"),
        payment_required=False,
    )

    result = OrderService(
        db,
        Settings(ghl_notifications_enabled=False, booking_hold_minutes=10, public_access_minutes=60),
    ).create(operator.slug, request, allow_payment_override=True)
    payment = db.scalar(select(Payment).where(Payment.booking_order_id == db.scalar(select(BookingOrder.id).where(BookingOrder.public_reference == result.public_reference))))
    assert result.status == "confirmed"
    assert result.payment_method == "none"
    assert result.invoice_url is None
    assert payment is not None and payment.payment_method == "none" and payment.status == "succeeded"
    assert db.scalar(select(OutboxJob).where(OutboxJob.job_type == "stripe_create_invoice")) is None


def test_authenticated_invoice_booking_creates_pending_invoice_job(db):
    operator, calendar = _operator_calendar(db)
    operator.public_booking_enabled = True
    calendar.public_booking_enabled = True
    db.add_all(
        [
            CalendarHour(calendar_id=calendar.id, day_of_week=day, start_time=time(0), end_time=time(23, 59))
            for day in range(7)
        ]
    )
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
    request = OrderCreateRequest(
        items=[OrderItemRequest(calendar_id=calendar.id, start_at=datetime(2027, 1, 5, 14, tzinfo=UTC), units=1)],
        customer=OrderCustomer(first_name="Invoice", last_name="Client", email="invoice@example.com"),
        payment_required=True,
    )

    result = OrderService(
        db,
        Settings(ghl_notifications_enabled=False, booking_hold_minutes=10, public_access_minutes=60),
    ).create(operator.slug, request, allow_payment_override=True)
    order = db.scalar(select(BookingOrder).where(BookingOrder.public_reference == result.public_reference))
    payment = db.scalar(select(Payment).where(Payment.booking_order_id == order.id))
    job = db.scalar(select(OutboxJob).where(OutboxJob.booking_order_id == order.id, OutboxJob.job_type == "stripe_create_invoice"))
    assert result.status == "pending_payment"
    assert result.payment_method == "invoice"
    assert payment is not None and payment.payment_method == "invoice" and payment.status == "requires_payment"
    assert job is not None and job.payload["payment_id"] == str(payment.id)


def test_invoice_termination_releases_pending_booking_and_syncs_appointment(db):
    operator, calendar = _operator_calendar(db)
    order = BookingOrder(
        operator_id=operator.id,
        public_reference=f"INV-{uuid.uuid4().hex[:10]}",
        customer_first_name="Alex",
        customer_last_name="Morgan",
        customer_email="alex@example.com",
        currency="usd",
        subtotal_minor=5000,
        platform_fee_and_taxes_minor=0,
        customer_total_minor=5000,
        operator_transfer_minor=0,
        platform_gross_retained_minor=0,
        status="pending_payment",
    )
    db.add(order)
    db.flush()
    payment = Payment(
        operator_id=operator.id,
        booking_order_id=order.id,
        payment_method="invoice",
        stripe_invoice_id="in_test_123",
        currency="usd",
        subtotal_minor=5000,
        platform_fee_and_taxes_minor=0,
        customer_total_minor=5000,
        operator_transfer_minor=0,
        platform_gross_retained_minor=0,
        status="requires_payment",
    )
    db.add(payment)
    db.flush()
    booking = Booking(
        operator_id=operator.id,
        booking_order_id=order.id,
        calendar_id=calendar.id,
        start_at=datetime.now(UTC) + timedelta(days=2),
        end_at=datetime.now(UTC) + timedelta(days=2, hours=1),
        units=1,
        base_price_minor=5000,
        status="pending_payment",
        hold_expires_at=datetime.now(UTC) + timedelta(minutes=10),
        calendar_name_snapshot=calendar.name,
    )
    db.add(booking)
    db.commit()

    StripeWebhookService(db)._invoice_terminated({"id": "in_test_123", "status": "void"})
    db.commit()

    db.refresh(order)
    db.refresh(payment)
    db.refresh(booking)
    assert order.status == "expired"
    assert payment.status == "failed"
    assert payment.invoice_status == "void"
    assert booking.status == "failed"
    assert booking.hold_expires_at is None
    job = db.scalar(
        select(OutboxJob).where(
            OutboxJob.idempotency_key == f"booking:{booking.id}:ghl_appointment:invoice-terminated"
        )
    )
    assert job is not None
    assert job.job_type == "ghl_sync_appointment"
