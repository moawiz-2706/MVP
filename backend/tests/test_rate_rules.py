import os
import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.exceptions import ConflictError
from app.models.entities import (
    Booking,
    BookingOrder,
    Calendar,
    CalendarHour,
    CalendarRate,
    CalendarRateResource,
    CustomerType,
    Operator,
    Resource,
)
from app.schemas.booking import BookingUpdate
from app.schemas.configuration import CalendarRatesReplace
from app.schemas.order import OrderCreateRequest, OrderCustomer, OrderItemRequest
from app.services.availability_service import AvailabilityService
from app.services.booking_admin_service import BookingAdminService
from app.services.configuration_service import ConfigurationService
from app.services.order_service import OrderService
from app.utils.timezone import local_datetime

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)

TZ = "America/New_York"
DAY = date(2027, 3, 10)
SETTINGS = Settings(ghl_notifications_enabled=False, ghl_sync_mode="disabled")


def _at(hour: int, minute: int = 0) -> datetime:
    return local_datetime(DAY, time(hour, minute), TZ)


def _operator(db) -> Operator:
    operator = Operator(ghl_location_id=f"loc-{uuid.uuid4().hex}", name="Punta Gorda", slug=f"pga-{uuid.uuid4().hex[:8]}",
                        time_zone=TZ, public_booking_enabled=True)
    db.add(operator)
    db.flush()
    return operator


def _calendar(db, operator, name, *, duration, interval, open_at, close_at, max_units=None) -> Calendar:
    calendar = Calendar(operator_id=operator.id, name=name, slug=f"c-{uuid.uuid4().hex[:8]}", duration_minutes=duration,
                        slot_interval_minutes=interval, base_price_minor=0, availability_mode="day_wise", is_active=True,
                        public_booking_enabled=True, required_staff_roles=[], max_units_per_booking=max_units)
    db.add(calendar)
    db.flush()
    db.add_all([CalendarHour(calendar_id=calendar.id, day_of_week=d, start_time=open_at, end_time=close_at) for d in range(7)])
    db.flush()
    return calendar


def _rate(db, operator, calendar, name, price, *, seats=None, resource=None, **rules) -> CalendarRate:
    customer_type = CustomerType(operator_id=operator.id, name=f"{name} {uuid.uuid4().hex[:4]}", plural_name=name, seat_count=1)
    db.add(customer_type)
    db.flush()
    rate = CalendarRate(operator_id=operator.id, calendar_id=calendar.id, customer_type_id=customer_type.id,
                        name_snapshot=name, price_minor=price, **rules)
    db.add(rate)
    db.flush()
    if resource is not None:
        db.add(CalendarRateResource(rate_id=rate.id, resource_id=resource.id, quantity_per_unit=seats))
        db.flush()
    return rate


def _book(db, operator, calendar, rate, start, quantity) -> Booking:
    request = OrderCreateRequest(
        items=[OrderItemRequest(calendar_id=calendar.id, rate_id=rate.id, start_at=start, quantity=quantity)],
        customer=OrderCustomer(first_name="Test", last_name="Guest", email="guest@example.com"),
        payment_required=False,
    )
    result = OrderService(db, SETTINGS).create(operator.slug, request, allow_payment_override=True)
    order_id = db.scalar(select(BookingOrder.id).where(BookingOrder.public_reference == result.public_reference))
    return db.scalar(select(Booking).where(Booking.booking_order_id == order_id))


@pytest.fixture()
def boat(db):
    """The Oasis: 30 shared seats, a public cruise and a private charter calendar."""
    operator = _operator(db)
    seats = Resource(operator_id=operator.id, name="The Oasis Tiki Seats", quantity=30)
    db.add(seats)
    db.flush()
    sunset = _calendar(db, operator, "Sunset Cruise", duration=120, interval=120, open_at=time(16, 30), close_at=time(18, 30))
    private = _calendar(db, operator, "Private Cruise", duration=120, interval=150, open_at=time(10), close_at=time(22), max_units=1)
    adult = _rate(db, operator, sunset, "Adult", 5900, resource=seats, seats=1)
    child = _rate(db, operator, sunset, "Child", 3500, resource=seats, seats=1, max_units_per_departure=10)
    two_hour = _rate(db, operator, private, "Private 2 Hour", 160000, resource=seats, seats=30)
    eight_hour = _rate(db, operator, private, "Private 8 Hour", 325000, resource=seats, seats=30, duration_minutes=480)
    db.commit()
    return operator, seats, sunset, private, adult, child, two_hour, eight_hour


def _slots(db, operator, calendar):
    day = AvailabilityService(db).calendar_day(calendar.id, operator.id, DAY)
    return {slot.start_at.astimezone(UTC): {rate.rate_id: rate for rate in slot.rates} for slot in day.slots}


def test_a_long_charter_holds_the_boat_for_its_own_length(db, boat):
    operator, seats, sunset, private, adult, child, two_hour, eight_hour = boat

    before = _slots(db, operator, private)[_at(10).astimezone(UTC)]
    assert before[eight_hour.id].duration_minutes == 480 and before[two_hour.id].duration_minutes == 120

    booking = _book(db, operator, private, eight_hour, _at(10), 1)
    assert booking.end_at - booking.start_at == timedelta(hours=8)

    private_slots = _slots(db, operator, private)
    # 10:00–18:00 takes all 30 seats: 12:30 and 3:00 charters are gone, 8:00 PM is not.
    assert private_slots[_at(12, 30).astimezone(UTC)][two_hour.id].available_quantity == 0
    assert private_slots[_at(15).astimezone(UTC)][two_hour.id].available_quantity == 0
    assert private_slots[_at(20).astimezone(UTC)][two_hour.id].available_quantity == 1
    # ...and the public 4:30 PM sunset cruise on the same boat is sold out.
    assert _slots(db, operator, sunset)[_at(16, 30).astimezone(UTC)][adult.id].available_quantity == 0
    with pytest.raises(ConflictError):
        _book(db, operator, sunset, adult, _at(16, 30), 2)


def test_an_8_hour_option_at_noon_cannot_overrun_a_later_public_booking(db, boat):
    operator, seats, sunset, private, adult, child, two_hour, eight_hour = boat
    _book(db, operator, sunset, adult, _at(16, 30), 1)

    slots = _slots(db, operator, private)[_at(12, 30).astimezone(UTC)]
    assert slots[two_hour.id].available_quantity == 1  # 12:30–2:30 is clear
    assert slots[eight_hour.id].available_quantity == 0  # 12:30–8:30 PM collides with the cruise
    with pytest.raises(ConflictError):
        _book(db, operator, private, eight_hour, _at(12, 30), 1)


def test_children_are_capped_per_departure_across_bookings(db, boat):
    operator, seats, sunset, private, adult, child, two_hour, eight_hour = boat
    _book(db, operator, sunset, child, _at(16, 30), 6)

    slot = _slots(db, operator, sunset)[_at(16, 30).astimezone(UTC)]
    assert slot[child.id].available_quantity == 4 and slot[adult.id].available_quantity == 24
    with pytest.raises(ConflictError, match="Only 4"):
        _book(db, operator, sunset, child, _at(16, 30), 5)
    _book(db, operator, sunset, child, _at(16, 30), 4)
    assert _slots(db, operator, sunset)[_at(16, 30).astimezone(UTC)][child.id].available_quantity == 0


def test_group_size_tiers_like_the_escape_room(db):
    operator = _operator(db)
    game = _calendar(db, operator, "Escape Room", duration=60, interval=120, open_at=time(9), close_at=time(20))
    small = _rate(db, operator, game, "1 - 2 Players", 2900, min_units_per_booking=1, max_units_per_booking=2)
    trio = _rate(db, operator, game, "3 Players", 2500, min_units_per_booking=3, max_units_per_booking=3)
    group = _rate(db, operator, game, "4 - 7 Players", 2200, min_units_per_booking=4, max_units_per_booking=7)
    db.commit()

    slot = _slots(db, operator, game)[_at(9).astimezone(UTC)]
    assert [slot[rate.id].available_quantity for rate in (small, trio, group)] == [2, 3, 7]
    assert slot[group.id].min_units_per_booking == 4
    with pytest.raises(ConflictError, match="at least 4"):
        _book(db, operator, game, group, _at(9), 3)
    with pytest.raises(ConflictError, match="at most 2"):
        _book(db, operator, game, small, _at(9), 3)
    booking = _book(db, operator, game, group, _at(9), 5)
    assert booking.units == 5


def test_saving_rates_without_the_new_fields_keeps_them(db, boat):
    operator, seats, sunset, private, adult, child, two_hour, eight_hour = boat
    payload = CalendarRatesReplace.model_validate({"rates": [
        {"customer_type_id": str(rate.customer_type_id), "price_minor": rate.price_minor,
         "resources": [{"resource_id": str(seats.id), "quantity_per_unit": 30}]}
        for rate in (two_hour, eight_hour)
    ]})
    ConfigurationService(db, operator.id).replace_calendar_rates(private.id, payload)
    db.expire_all()
    assert db.get(CalendarRate, eight_hour.id).duration_minutes == 480


def test_editing_a_long_charter_keeps_its_length(db, boat):
    operator, seats, sunset, private, adult, child, two_hour, eight_hour = boat
    six_hour = _rate(db, operator, private, "Private 6 Hour", 290000, resource=seats, seats=30, duration_minutes=360)
    db.commit()
    booking = _book(db, operator, private, six_hour, _at(10), 1)

    BookingAdminService(db, operator.id).update(booking.id, BookingUpdate(start_at=_at(12, 30)))
    db.expire_all()
    moved = db.get(Booking, booking.id)
    assert moved.start_at == _at(12, 30).astimezone(UTC) and moved.end_at - moved.start_at == timedelta(hours=6)


def test_month_view_marks_open_and_sold_out_days(db, boat):
    operator, seats, sunset, private, adult, child, two_hour, eight_hour = boat
    # Sell out the 10th: a full-day charter takes the whole boat at the sunset hour.
    _book(db, operator, private, eight_hour, _at(10), 1)

    month = AvailabilityService(db).public_month(operator.slug, sunset.slug, 2027, 3)
    by_day = {day["date"]: day["status"] for day in month["days"]}
    assert len(by_day) == 31 and month["time_zone"] == TZ
    assert by_day[date(2027, 3, 10)] == "sold_out"
    assert by_day[date(2027, 3, 11)] == "available"
