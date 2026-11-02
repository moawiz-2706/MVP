"""Checks that only exist in the real migration chain, not in the ORM models.

The rest of the suite builds tables from SQLAlchemy metadata, which cannot
express exclusion constraints, generated columns, triggers or RLS. These tests
run against a database built by applying supabase/migrations in order:

    TEST_MIGRATED_DATABASE_URL=postgresql+psycopg://postgres@localhost:55432/passport_migrations

Every test runs inside a transaction that is rolled back, so the database is
left unchanged.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.entities import Booking, BookingEvent, BookingOrder, Calendar, Operator, Staff, StaffAssignment

MIGRATED_URL = os.getenv("TEST_MIGRATED_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not MIGRATED_URL, reason="Set TEST_MIGRATED_DATABASE_URL to a database built from supabase/migrations"
)


@pytest.fixture()
def migrated():
    engine = create_engine(MIGRATED_URL, future=True)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def _operator_calendar(session):
    operator = Operator(ghl_location_id=f"loc-{uuid.uuid4().hex}", name="Op", slug=f"op-{uuid.uuid4().hex[:8]}", time_zone="UTC")
    session.add(operator)
    session.flush()
    calendars = []
    for name in ("Morning Tour", "Rental"):
        calendar = Calendar(operator_id=operator.id, name=name, slug=f"c-{uuid.uuid4().hex[:8]}", duration_minutes=60,
                            slot_interval_minutes=60, base_price_minor=0)
        session.add(calendar)
        calendars.append(calendar)
    session.flush()
    return operator, calendars


def _assign(session, operator, staff, calendar, start, hours=2):
    session.add(StaffAssignment(operator_id=operator.id, staff_id=staff.id, calendar_id=calendar.id,
                                start_at=start, end_at=start + timedelta(hours=hours)))
    session.flush()


def test_one_person_cannot_be_assigned_to_overlapping_trips(migrated):
    operator, (tour, rental) = _operator_calendar(migrated)
    guide = Staff(operator_id=operator.id, name="Guide", is_active=True)
    migrated.add(guide)
    migrated.flush()
    start = datetime(2027, 3, 1, 9, tzinfo=UTC)
    _assign(migrated, operator, guide, tour, start)

    with pytest.raises(DBAPIError) as conflict:
        with migrated.begin_nested():
            _assign(migrated, operator, guide, rental, start + timedelta(hours=1))
    assert "staff_assignments_no_overlap" in str(conflict.value)
    # Back-to-back is not an overlap ([start, end) ranges).
    _assign(migrated, operator, guide, rental, start + timedelta(hours=2))


def test_several_staff_can_share_one_departure(migrated):
    operator, (tour, _rental) = _operator_calendar(migrated)
    start = datetime(2027, 3, 1, 9, tzinfo=UTC)
    for name in ("Captain", "Guide", "Trainee"):
        member = Staff(operator_id=operator.id, name=name, is_active=True)
        migrated.add(member)
        migrated.flush()
        _assign(migrated, operator, member, tour, start)
    count = migrated.scalar(text("SELECT count(*) FROM staff_assignments WHERE calendar_id = :c"), {"c": tour.id})
    assert count == 3


def test_booking_history_is_append_only(migrated):
    operator, (tour, _rental) = _operator_calendar(migrated)
    order = BookingOrder(operator_id=operator.id, public_reference=f"RM-{uuid.uuid4().hex[:10]}", customer_first_name="A",
                         customer_last_name="B", customer_email="a@example.com", subtotal_minor=0,
                         platform_fee_and_taxes_minor=0, customer_total_minor=0, operator_transfer_minor=0,
                         platform_gross_retained_minor=0, status="confirmed", booking_source="pwa")
    migrated.add(order)
    migrated.flush()
    start = datetime(2027, 3, 1, 9, tzinfo=UTC)
    booking = Booking(operator_id=operator.id, booking_order_id=order.id, calendar_id=tour.id, start_at=start,
                      end_at=start + timedelta(hours=1), units=1, base_price_minor=0, status="confirmed",
                      calendar_name_snapshot=tour.name)
    migrated.add(booking)
    migrated.flush()
    event = BookingEvent(operator_id=operator.id, booking_id=booking.id, order_id=order.id, event_type="checked_in",
                         actor_type="operator", occurred_at=start)
    migrated.add(event)
    migrated.flush()

    with pytest.raises(DBAPIError):
        with migrated.begin_nested():
            migrated.execute(text("UPDATE booking_events SET reason = 'edited' WHERE id = :id"), {"id": event.id})


def test_invalid_booking_source_is_rejected(migrated):
    operator, _calendars = _operator_calendar(migrated)
    with pytest.raises(DBAPIError):
        with migrated.begin_nested():
            migrated.add(BookingOrder(operator_id=operator.id, public_reference=f"RM-{uuid.uuid4().hex[:10]}",
                                      customer_first_name="A", customer_last_name="B", customer_email="a@example.com",
                                      subtotal_minor=0, platform_fee_and_taxes_minor=0, customer_total_minor=0,
                                      operator_transfer_minor=0, platform_gross_retained_minor=0, status="confirmed",
                                      booking_source="walk_in"))
            migrated.flush()


def test_supabase_data_api_roles_see_no_rows(migrated):
    _operator_calendar(migrated)
    unprotected = migrated.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND NOT rowsecurity"))
    assert unprotected == 0
    with migrated.begin_nested():
        migrated.execute(text("GRANT SELECT ON public.operators TO anon"))
        migrated.execute(text("SET LOCAL ROLE anon"))
        visible = migrated.scalar(text("SELECT count(*) FROM public.operators"))
        migrated.execute(text("RESET ROLE"))
    assert visible == 0
