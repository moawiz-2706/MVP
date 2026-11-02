import os
import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest

from app.models.entities import (
    Booking,
    BookingOrder,
    BookingResource,
    Calendar,
    CalendarBlock,
    CalendarHour,
    CalendarPushedSlot,
    CalendarRate,
    CalendarRateResource,
    CustomerType,
    Operator,
    Payment,
    Resource,
    Staff,
    StaffAssignment,
)
from app.services.departure_board_service import DepartureBoardService
from app.utils.timezone import local_datetime

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)

TZ = "America/New_York"
DAY = date(2027, 6, 18)  # a Friday


def _local(hour: int, minute: int = 0) -> datetime:
    return local_datetime(DAY, time(hour, minute), TZ)


def _operator(db) -> Operator:
    operator = Operator(
        ghl_location_id=f"loc-{uuid.uuid4().hex}",
        name="Kayak Operator",
        slug=f"kayak-{uuid.uuid4().hex[:8]}",
        time_zone=TZ,
    )
    db.add(operator)
    db.flush()
    return operator


def _calendar(db, operator, name, *, mode="day_wise", duration=120) -> Calendar:
    calendar = Calendar(
        operator_id=operator.id,
        name=name,
        slug=f"cal-{uuid.uuid4().hex[:8]}",
        duration_minutes=duration,
        slot_interval_minutes=30,
        base_price_minor=0,
        availability_mode=mode,
        is_active=True,
        public_booking_enabled=True,
        required_staff_roles=[],
    )
    db.add(calendar)
    db.flush()
    return calendar


def _sell(db, operator, calendar, resource, type_name="Single Kayak") -> None:
    customer_type = CustomerType(
        operator_id=operator.id, name=f"{type_name} ({calendar.name})", plural_name=f"{type_name}s", seat_count=1
    )
    db.add(customer_type)
    db.flush()
    rate = CalendarRate(
        operator_id=operator.id,
        calendar_id=calendar.id,
        customer_type_id=customer_type.id,
        name_snapshot=type_name,
        price_minor=4000,
    )
    db.add(rate)
    db.flush()
    db.add(CalendarRateResource(rate_id=rate.id, resource_id=resource.id))
    db.flush()


def _booking(
    db, operator, calendar, resource, *, start, qty, status="confirmed", hold=None, last="Lovelace"
) -> Booking:
    order = BookingOrder(
        operator_id=operator.id,
        public_reference=f"RM-{uuid.uuid4().hex[:12]}",
        customer_first_name="Ada",
        customer_last_name=last,
        customer_email="ada@example.com",
        subtotal_minor=0,
        platform_fee_and_taxes_minor=0,
        customer_total_minor=0,
        operator_transfer_minor=0,
        platform_gross_retained_minor=0,
        status="confirmed" if status == "confirmed" else "pending_payment",
    )
    db.add(order)
    db.flush()
    db.add(
        Payment(
            operator_id=operator.id,
            booking_order_id=order.id,
            currency="usd",
            subtotal_minor=0,
            platform_fee_and_taxes_minor=0,
            customer_total_minor=0,
            operator_transfer_minor=0,
            platform_gross_retained_minor=0,
            payment_method="card",
            status="succeeded" if status == "confirmed" else "processing",
        )
    )
    booking = Booking(
        operator_id=operator.id,
        booking_order_id=order.id,
        calendar_id=calendar.id,
        start_at=start,
        end_at=start + timedelta(minutes=calendar.duration_minutes),
        units=qty,
        base_price_minor=4000,
        status=status,
        hold_expires_at=hold,
        calendar_name_snapshot=calendar.name,
    )
    db.add(booking)
    db.flush()
    db.add(BookingResource(booking_id=booking.id, resource_id=resource.id, quantity=qty))
    db.flush()
    return booking


@pytest.fixture()
def kayaks(db):
    operator = _operator(db)
    tour = _calendar(db, operator, "Swamp Tour")
    rental = _calendar(db, operator, "Kayak Rental")
    singles = Resource(operator_id=operator.id, name="Single Kayaks", quantity=20)
    tandems = Resource(operator_id=operator.id, name="Tandem Kayaks", quantity=6)
    db.add_all([singles, tandems])
    db.flush()
    for calendar in (tour, rental):
        db.add(CalendarHour(calendar_id=calendar.id, day_of_week=4, start_time=time(8), end_time=time(12)))
    _sell(db, operator, tour, singles)
    _sell(db, operator, tour, tandems, "Tandem Kayak")
    _sell(db, operator, rental, singles)
    db.commit()
    return operator, tour, rental, singles, tandems


def _for(response, calendar, start):
    return next(
        item
        for item in response.departures
        if item.calendar_id == calendar.id and item.start_at == start.astimezone(UTC)
    )


def test_every_configured_departure_is_listed_even_without_bookings(db, kayaks):
    operator, tour, rental, singles, tandems = kayaks
    board = DepartureBoardService(db, operator.id).day(DAY)

    tour_starts = [item.start_at for item in board.departures if item.calendar_id == tour.id]
    assert tour_starts == [_local(h, m).astimezone(UTC) for h, m in ((8, 0), (8, 30), (9, 0), (9, 30), (10, 0))]
    assert board.time_zone == TZ
    first = _for(board, tour, _local(8))
    assert first.source == "scheduled"
    assert first.bookings == [] and first.booked_units == 0
    assert [(r.name, r.total, r.confirmed, r.held, r.remaining) for r in first.resources] == [
        ("Single Kayaks", 20, 0, 0, 20),
        ("Tandem Kayaks", 6, 0, 0, 6),
    ]


def test_shared_resources_reconcile_across_calendars_and_unit_types_stay_separate(db, kayaks):
    operator, tour, rental, singles, tandems = kayaks
    _booking(db, operator, rental, singles, start=_local(9), qty=5)
    _booking(db, operator, tour, tandems, start=_local(9), qty=2, last="Hopper")
    db.commit()

    board = DepartureBoardService(db, operator.id).day(DAY)
    tour_nine = _for(board, tour, _local(9))
    by_name = {r.name: r for r in tour_nine.resources}
    # The rental's 5 singles reduce the tour's shared pool; tandems are separate.
    assert (by_name["Single Kayaks"].confirmed, by_name["Single Kayaks"].remaining) == (5, 15)
    assert (by_name["Tandem Kayaks"].confirmed, by_name["Tandem Kayaks"].remaining) == (2, 4)
    assert [b.lead_name for b in tour_nine.bookings] == ["Ada Hopper"]
    # 8:00-10:00 overlaps the 9:00 rental, so its singles are consumed too.
    assert {r.name: r.remaining for r in _for(board, tour, _local(8)).resources}["Single Kayaks"] == 15
    # 11:00 departures do not exist (11:00 + 2h passes the 12:00 close).
    assert all(item.start_at < _local(10, 30).astimezone(UTC) for item in board.departures)


def test_holds_count_as_held_and_inactive_bookings_are_listed_but_not_counted(db, kayaks):
    operator, tour, rental, singles, tandems = kayaks
    now = datetime.now(UTC)
    _booking(db, operator, tour, singles, start=_local(8), qty=3, status="pending_payment",
             hold=now + timedelta(minutes=10), last="Held")
    _booking(db, operator, tour, singles, start=_local(8), qty=4, status="pending_payment",
             hold=now - timedelta(minutes=1), last="Expired")
    _booking(db, operator, tour, singles, start=_local(8), qty=6, status="cancelled", last="Cancelled")
    db.commit()

    departure = _for(DepartureBoardService(db, operator.id).day(DAY), tour, _local(8))
    singles_row = next(r for r in departure.resources if r.name == "Single Kayaks")
    assert (singles_row.confirmed, singles_row.held, singles_row.remaining) == (0, 3, 17)
    assert {b.lead_name: b.status for b in departure.bookings} == {
        "Ada Cancelled": "cancelled",
        "Ada Expired": "pending_payment",
        "Ada Held": "pending_payment",
    }
    assert all(b.payment_status == "processing" for b in departure.bookings if b.status != "cancelled")
    # The expired hold no longer reserves inventory but is still a party on the list.
    assert departure.booked_units == 7


def test_booking_outside_configured_hours_appears_as_unscheduled(db, kayaks):
    operator, tour, rental, singles, tandems = kayaks
    _booking(db, operator, tour, singles, start=_local(15), qty=2)
    db.commit()

    departure = _for(DepartureBoardService(db, operator.id).day(DAY), tour, _local(15))
    assert departure.source == "unscheduled"
    assert departure.booked_units == 2


def test_pushed_calendar_lists_only_its_exact_departures(db, kayaks):
    operator, tour, rental, singles, tandems = kayaks
    sunset = _calendar(db, operator, "Sunset Paddle", mode="pushed", duration=90)
    _sell(db, operator, sunset, singles)
    for start in (_local(7, 15), _local(18, 40)):
        db.add(CalendarPushedSlot(calendar_id=sunset.id, start_at=start))
    db.commit()

    board = DepartureBoardService(db, operator.id).day(DAY, calendar_id=sunset.id)
    assert [(item.start_at, item.source) for item in board.departures] == [
        (_local(7, 15).astimezone(UTC), "pushed"),
        (_local(18, 40).astimezone(UTC), "pushed"),
    ]


def test_staff_blocks_and_tenant_isolation(db, kayaks):
    operator, tour, rental, singles, tandems = kayaks
    guide = Staff(operator_id=operator.id, name="River Guide", is_active=True)
    lead = Staff(operator_id=operator.id, name="Alex Lead", is_active=True)
    db.add_all([guide, lead])
    db.flush()
    for staff in (guide, lead):
        db.add(StaffAssignment(operator_id=operator.id, staff_id=staff.id, calendar_id=tour.id,
                               start_at=_local(9), end_at=_local(11), role="guide"))
    shift = Staff(operator_id=operator.id, name="Shift Captain", is_active=True)
    db.add(shift)
    db.flush()
    db.add(StaffAssignment(operator_id=operator.id, staff_id=shift.id, calendar_id=tour.id,
                           start_at=_local(8), end_at=_local(12), role="captain"))
    db.add(CalendarBlock(calendar_id=tour.id, start_at=_local(10), end_at=_local(12), reason="weather"))
    other = _operator(db)
    other_calendar = _calendar(db, other, "Other Tour")
    other_resource = Resource(operator_id=other.id, name="Boats", quantity=3)
    db.add(other_resource)
    db.flush()
    _booking(db, other, other_calendar, other_resource, start=_local(9), qty=1)
    db.commit()

    board = DepartureBoardService(db, operator.id).day(DAY)
    nine = _for(board, tour, _local(9))
    assert [s.staff_name for s in nine.staff] == ["Alex Lead", "River Guide", "Shift Captain"]
    # The 9:00 guides partially overlap 8:00 but are not on that trip; the
    # captain's 8:00-12:00 shift covers every departure.
    assert [s.staff_name for s in _for(board, tour, _local(8)).staff] == ["Shift Captain"]
    assert [s.staff_name for s in _for(board, tour, _local(10)).staff] == ["Shift Captain"]
    assert nine.blocked  # 9:00-11:00 overlaps the 10:00 weather block
    assert not _for(board, tour, _local(8)).blocked
    assert all(item.calendar_id in {tour.id, rental.id} for item in board.departures)
