import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models.entities import Booking, BookingOrder, Calendar, Operator, OutboxJob, Payment
from app.services import abandoned_checkout_service
from app.services.abandoned_checkout_service import AbandonedCheckoutService
from app.services.reservation_lifecycle_service import ReservationLifecycleService

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)


def _setup(db):
    operator = Operator(ghl_location_id=f"loc-{uuid.uuid4().hex}", name="Op", slug=f"op-{uuid.uuid4().hex[:8]}", time_zone="UTC")
    db.add(operator)
    db.flush()
    calendar = Calendar(operator_id=operator.id, name="Tour", slug=f"t-{uuid.uuid4().hex[:8]}", duration_minutes=60,
                        slot_interval_minutes=60, base_price_minor=0, availability_mode="day_wise", is_active=True,
                        public_booking_enabled=True, required_staff_roles=[])
    db.add(calendar)
    db.flush()
    return operator, calendar


def _checkout(db, operator, calendar, *, expired_ago, method="card", pay="processing", intent=True):
    order = BookingOrder(operator_id=operator.id, public_reference=f"RM-{uuid.uuid4().hex[:10]}", customer_first_name="Ada",
                         customer_last_name="Lovelace", customer_email="ada@example.com", subtotal_minor=4000,
                         platform_fee_and_taxes_minor=0, customer_total_minor=4000, operator_transfer_minor=4000,
                         platform_gross_retained_minor=0, status="pending_payment")
    db.add(order)
    db.flush()
    payment = Payment(operator_id=operator.id, booking_order_id=order.id, currency="usd", subtotal_minor=4000,
                      platform_fee_and_taxes_minor=0, customer_total_minor=4000, operator_transfer_minor=4000,
                      platform_gross_retained_minor=0, payment_method=method, status=pay,
                      stripe_payment_intent_id=f"pi_{uuid.uuid4().hex[:16]}" if intent else None)
    db.add(payment)
    start = datetime.now(UTC) + timedelta(days=2)
    booking = Booking(operator_id=operator.id, booking_order_id=order.id, calendar_id=calendar.id, start_at=start,
                      end_at=start + timedelta(hours=1), units=1, base_price_minor=4000, status="pending_payment",
                      hold_expires_at=datetime.now(UTC) - expired_ago, calendar_name_snapshot=calendar.name)
    db.add(booking)
    db.commit()
    return order, payment, booking


def _cancel_jobs(db, order):
    return list(db.scalars(select(OutboxJob).where(
        OutboxJob.booking_order_id == order.id, OutboxJob.job_type == "stripe_cancel_payment_intent")))


def test_card_checkout_inside_grace_is_kept_for_a_late_completion(db):
    operator, calendar = _setup(db)
    order, payment, booking = _checkout(db, operator, calendar, expired_ago=timedelta(minutes=5))

    ReservationLifecycleService(db).expire_pending_holds()
    db.refresh(booking)
    assert booking.status == "pending_payment"
    assert _cancel_jobs(db, order) == []


def test_abandoned_card_checkout_is_released_and_its_intent_cancel_queued_once(db):
    operator, calendar = _setup(db)
    order, payment, booking = _checkout(db, operator, calendar, expired_ago=timedelta(minutes=45))

    first = ReservationLifecycleService(db).expire_pending_holds()
    second = ReservationLifecycleService(db).expire_pending_holds()
    db.refresh(booking)
    db.refresh(order)
    assert booking.status == "cancelled" and order.status == "expired"
    assert first["expired_holds"] == 1 and second["expired_holds"] == 0
    jobs = _cancel_jobs(db, order)
    assert len(jobs) == 1 and jobs[0].payload == {"payment_id": str(payment.id)}


def test_invoice_and_paid_checkouts_never_queue_an_intent_cancel(db):
    operator, calendar = _setup(db)
    invoice_order, _, invoice_booking = _checkout(db, operator, calendar, expired_ago=timedelta(minutes=45),
                                                  method="invoice", pay="requires_payment", intent=False)
    paid_order, _, paid_booking = _checkout(db, operator, calendar, expired_ago=timedelta(hours=3), pay="succeeded")

    ReservationLifecycleService(db).expire_pending_holds()
    db.refresh(invoice_booking)
    db.refresh(paid_booking)
    assert invoice_booking.status == "cancelled"  # unchanged existing behaviour
    assert paid_booking.status == "pending_payment"  # a paid order is never released here
    assert _cancel_jobs(db, invoice_order) == [] and _cancel_jobs(db, paid_order) == []


class FakeStripe:
    def __init__(self, status):
        self.status = status
        self.cancelled_with = None

    def __call__(self, settings):
        return self

    def retrieve_payment_intent(self, intent_id):
        return SimpleNamespace(id=intent_id, status=self.status)

    def cancel_payment_intent(self, intent_id, *, idempotency_key):
        self.cancelled_with = idempotency_key
        return SimpleNamespace(id=intent_id, status="canceled")


@pytest.mark.parametrize(
    ("stripe_status", "result", "payment_status"),
    [("requires_payment_method", "canceled", "failed"), ("succeeded", "succeeded", "processing")],
)
def test_cancel_intent_job(db, monkeypatch, stripe_status, result, payment_status):
    operator, calendar = _setup(db)
    order, payment, booking = _checkout(db, operator, calendar, expired_ago=timedelta(minutes=45))
    ReservationLifecycleService(db).expire_pending_holds()
    fake = FakeStripe(stripe_status)
    monkeypatch.setattr(abandoned_checkout_service, "StripePaymentService", fake)

    assert AbandonedCheckoutService(db, Settings()).cancel_intent(payment.id) == result
    db.refresh(payment)
    # A customer who paid at the last moment is left to the verified webhook,
    # which refunds a payment for a released booking.
    assert payment.status == payment_status
    if result == "canceled":
        assert fake.cancelled_with == f"payment:{payment.id}:abandoned-cancel"


def test_cancel_intent_skips_an_order_that_is_active_again(db, monkeypatch):
    operator, calendar = _setup(db)
    order, payment, booking = _checkout(db, operator, calendar, expired_ago=timedelta(minutes=1))
    monkeypatch.setattr(abandoned_checkout_service, "StripePaymentService", FakeStripe("requires_payment_method"))

    assert AbandonedCheckoutService(db, Settings()).cancel_intent(payment.id) == "skipped"
