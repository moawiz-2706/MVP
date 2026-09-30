"""Focused tests for centralized policy and lifecycle financial outcomes."""

import os
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.exceptions import ConflictError
from app.models.entities import (
    Booking,
    BookingAdjustment,
    BookingOrder,
    CalendarBookingPolicy,
    OutboxJob,
    Payment,
    PaymentRefundAttempt,
)
from app.schemas.booking import BookingUpdate
from app.services.booking_lifecycle_service import BookingLifecycleService
from app.services.policy_service import PolicyService
from tests.test_waivers_integration import _booking, _calendar, _operator, _tomorrow

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)


def _paid_booking(db, *, total: int = 10_000, units: int = 2):
    operator = _operator(db)
    calendar = _calendar(db, operator)
    booking = _booking(db, operator, calendar, units=units)
    order = db.get(BookingOrder, booking.booking_order_id)
    payment = db.scalar(select(Payment).where(Payment.booking_order_id == order.id))
    assert order is not None and payment is not None
    order.subtotal_minor = total
    order.customer_total_minor = total
    payment.subtotal_minor = total
    payment.customer_total_minor = total
    booking.base_price_minor = total // units
    booking.line_subtotal_minor = total
    booking.line_total_minor = total
    db.commit()
    return operator, calendar, booking, order, payment


def test_policy_resolution_uses_booking_snapshot(db) -> None:
    operator, calendar, booking, _order, _payment = _paid_booking(db)
    first = CalendarBookingPolicy(
        operator_id=operator.id,
        calendar_id=calendar.id,
        version=1,
        cancellation_fee_bps=2_500,
    )
    second = CalendarBookingPolicy(
        operator_id=operator.id,
        calendar_id=calendar.id,
        version=2,
        cancellation_fee_bps=0,
    )
    db.add_all([first, second])
    booking.booking_policy_version = 1
    db.commit()

    snapshot = PolicyService(db).resolve_for_booking(booking)
    assert snapshot.version == 1
    assert snapshot.cancellation_fee_bps == 2_500


def test_cancel_creates_idempotent_refund_adjustment_and_outbox(db) -> None:
    operator, _calendar, booking, _order, _payment = _paid_booking(db)
    result = BookingLifecycleService(db, operator.id).cancel(
        booking.id, force=True, reason="customer request", actor_type="customer"
    )
    db.expire_all()
    adjustment = db.scalar(select(BookingAdjustment).where(BookingAdjustment.booking_id == booking.id))
    assert result["status"] == "cancelled"
    assert adjustment is not None
    assert adjustment.action == "refund"
    assert adjustment.amount_minor == 10_000
    assert adjustment.original_amount_minor == 10_000
    assert db.scalar(select(PaymentRefundAttempt).where(PaymentRefundAttempt.payment_id == adjustment.payment_id))
    assert db.scalar(
        select(OutboxJob).where(
            OutboxJob.job_type == "stripe_create_refund",
            OutboxJob.booking_order_id == booking.booking_order_id,
        )
    )

    second = BookingLifecycleService(db, operator.id).cancel(booking.id, force=True)
    assert second["idempotent"] is True
    assert db.query(BookingAdjustment).filter(BookingAdjustment.booking_id == booking.id).count() == 1


def test_weather_credit_is_a_nonzero_ledger_entry(db) -> None:
    operator, _calendar, booking, _order, _payment = _paid_booking(db)
    result = BookingLifecycleService(db, operator.id).weather_cancel(
        booking.id,
        closure_id=booking.id,
        mode="credit",
        reason="unsafe weather",
        actor_id=None,
    )
    adjustment = db.scalar(select(BookingAdjustment).where(BookingAdjustment.booking_id == booking.id))
    assert result["status"] == "cancelled"
    assert adjustment is not None
    assert adjustment.action == "credit"
    assert adjustment.amount_minor == 10_000
    assert adjustment.status == "completed"
    assert adjustment.adjustment_metadata["credit_ledger"] is True


def test_no_show_partial_refund_uses_policy_and_event(db) -> None:
    operator, calendar, booking, _order, _payment = _paid_booking(db)
    db.add(
        CalendarBookingPolicy(
            operator_id=operator.id,
            calendar_id=calendar.id,
            version=1,
            no_show_mode="partial_refund",
        )
    )
    booking.booking_policy_version = 1
    db.commit()

    result = BookingLifecycleService(db, operator.id).set_status(
        booking.id, "no_show", reason="customer did not arrive"
    )
    adjustment = db.scalar(select(BookingAdjustment).where(BookingAdjustment.booking_id == booking.id))
    assert result["status"] == "no_show"
    assert adjustment is not None and adjustment.action == "refund"
    assert adjustment.amount_minor == 5_000


def test_paid_reschedule_price_increase_is_not_silent(db) -> None:
    operator, _calendar, booking, _order, _payment = _paid_booking(db, total=10_000, units=1)
    old_start = booking.start_at
    with pytest.raises(ConflictError, match="Additional payment is required"):
        BookingLifecycleService(db, operator.id).reschedule(
            booking.id,
            BookingUpdate(start_at=old_start + timedelta(days=1), units=2),
            reason="customer change",
            force=True,
        )
    db.refresh(booking)
    assert booking.start_at == old_start
    assert db.query(BookingAdjustment).filter(BookingAdjustment.booking_id == booking.id).count() == 0
