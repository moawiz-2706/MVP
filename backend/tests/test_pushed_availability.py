"""DB-backed tests for push availability (availability_mode = 'pushed').

Only explicitly pushed start instants are bookable. The end is start + duration,
slot_interval_minutes and opening hours are ignored, and blocks plus resource
inventory apply exactly as in the other modes. Gated on TEST_DATABASE_URL.
"""

import os
import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest

from app.core.exceptions import ConflictError
from app.models.entities import (
    Booking,
    BookingOrder,
    BookingResource,
    Calendar,
    CalendarBlock,
    CalendarDateHour,
    CalendarHour,
    CalendarPushedSlot,
    CalendarResource,
    Operator,
    Resource,
    Staff,
    StaffAssignment,
    StaffHour,
)
from app.schemas.configuration import PushedSlotsCreate, PushedSlotWrite
from app.services.availability_service import AvailabilityService
from app.services.booking_admin_service import BookingAdminService
from app.services.configuration_service import ConfigurationService
from app.utils.timezone import local_datetime

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)

TZ = "America/New_York"
DAY = date(2027, 6, 15)


def _at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return local_datetime(day, time(hour, minute), TZ)


def _setup(db, *, duration: int = 180):
    op = Operator(
        ghl_location_id=f"loc-{uuid.uuid4()}",
        name="Punta Gorda Rentals",
        slug=f"op-{uuid.uuid4().hex[:8]}",
        time_zone=TZ,
    )
    db.add(op)
    db.flush()
    cal = Calendar(
        operator_id=op.id,
        name="Sunset Cruise",
        slug=f"cal-{uuid.uuid4().hex[:8]}",
        duration_minutes=duration,
        slot_interval_minutes=30,
        base_price_minor=7000,
        availability_mode="pushed",
    )
    db.add(cal)
    db.flush()
    captain = Staff(
        operator_id=op.id,
        name="Test Captain",
        custom_role="Captain",
        is_active=True,
    )
    db.add(captain)
    db.flush()
    db.add_all(
        [
            StaffHour(
                staff_id=captain.id,
                day_of_week=dow,
                start_time=time(0),
                end_time=time(23, 59),
            )
            for dow in range(7)
        ]
    )
    db.add(
        StaffAssignment(
            operator_id=op.id,
            staff_id=captain.id,
            calendar_id=cal.id,
            start_at=_at(0),
            end_at=_at(0, day=DAY + timedelta(days=1)),
            role="Captain",
        )
    )
    db.flush()
    return op, cal


def _push(db, cal, *starts: datetime) -> None:
    db.add_all([CalendarPushedSlot(calendar_id=cal.id, start_at=start) for start in starts])
    db.flush()


def _book(db, op, cal, res, start: datetime, qty: int) -> None:
    order = BookingOrder(
        operator_id=op.id,
        public_reference=f"RM-{uuid.uuid4().hex[:12]}",
        customer_first_name="Ada",
        customer_last_name="Lovelace",
        customer_email="ada@example.com",
        subtotal_minor=0,
        platform_fee_and_taxes_minor=0,
        customer_total_minor=0,
        operator_transfer_minor=0,
        platform_gross_retained_minor=0,
        status="confirmed",
    )
    db.add(order)
    db.flush()
    booking = Booking(
        operator_id=op.id,
        booking_order_id=order.id,
        calendar_id=cal.id,
        start_at=start,
        end_at=start + timedelta(minutes=cal.duration_minutes),
        units=qty,
        base_price_minor=7000,
        status="confirmed",
        calendar_name_snapshot=cal.name,
    )
    db.add(booking)
    db.flush()
    db.add(BookingResource(booking_id=booking.id, resource_id=res.id, quantity=qty))
    db.flush()


def test_pushed_start_is_available_with_end_from_duration(db) -> None:
    op, cal = _setup(db)
    _push(db, cal, _at(9))
    db.commit()
    result = AvailabilityService(db).check(cal.id, _at(9), 1, operator_id=op.id)
    assert result.available
    assert result.end_at == _at(12)


def test_unpushed_start_is_unavailable(db) -> None:
    op, cal = _setup(db)
    _push(db, cal, _at(9))
    db.commit()
    result = AvailabilityService(db).check(cal.id, _at(9, 30), 1, operator_id=op.id)
    assert not result.available
    assert result.max_bookable_units == 0


def test_slot_interval_is_ignored(db) -> None:
    # 09:17 is not on the 30-minute grid, but it was pushed, so it is bookable.
    op, cal = _setup(db)
    _push(db, cal, _at(9, 17))
    db.commit()
    assert AvailabilityService(db).check(cal.id, _at(9, 17), 1, operator_id=op.id).available


def test_weekly_hours_are_ignored_in_pushed_mode(db) -> None:
    op, cal = _setup(db)
    for dow in range(7):
        db.add(CalendarHour(calendar_id=cal.id, day_of_week=dow, start_time=time(8), end_time=time(18)))
    db.commit()
    assert not AvailabilityService(db).check(cal.id, _at(10), 1, operator_id=op.id).available


def test_date_wise_ranges_are_ignored_in_pushed_mode(db) -> None:
    op, cal = _setup(db)
    db.add(CalendarDateHour(calendar_id=cal.id, start_date=DAY, end_date=DAY, start_time=time(8), end_time=time(18)))
    db.commit()
    assert not AvailabilityService(db).check(cal.id, _at(10), 1, operator_id=op.id).available
    assert AvailabilityService(db).public_day(op.slug, cal.slug, DAY).slots == []


@pytest.mark.parametrize("mode", ["day_wise", "date_wise"])
def test_pushed_slots_are_ignored_outside_pushed_mode(db, mode) -> None:
    # Pushed rows are kept when the calendar switches mode, but never count.
    op, cal = _setup(db)
    cal.availability_mode = mode
    _push(db, cal, _at(9, 17))
    db.commit()
    assert not AvailabilityService(db).check(cal.id, _at(9, 17), 1, operator_id=op.id).available
    assert AvailabilityService(db).public_day(op.slug, cal.slug, DAY).slots == []


def test_pushed_slot_consumes_shared_resources(db) -> None:
    op, cal = _setup(db)
    res = Resource(operator_id=op.id, name="Boats", quantity=2)
    db.add(res)
    db.flush()
    db.add(CalendarResource(calendar_id=cal.id, resource_id=res.id, default_quantity_per_unit=1))
    _push(db, cal, _at(9))
    _book(db, op, cal, res, _at(9), 2)
    db.commit()
    result = AvailabilityService(db).check(cal.id, _at(9), 1, operator_id=op.id)
    assert not result.available
    assert result.reason == "Insufficient resource inventory"


def test_blocks_apply_to_pushed_slots(db) -> None:
    op, cal = _setup(db)
    _push(db, cal, _at(9))
    db.add(CalendarBlock(calendar_id=cal.id, start_at=_at(0), end_at=_at(0, day=DAY + timedelta(days=1))))
    db.commit()
    result = AvailabilityService(db).check(cal.id, _at(9), 1, operator_id=op.id)
    assert result.reason == "Requested time is blocked"


def test_public_day_lists_only_that_days_pushed_slots(db) -> None:
    op, cal = _setup(db)
    _push(db, cal, _at(9), _at(14, 45), _at(9, day=DAY + timedelta(days=1)))
    db.commit()
    response = AvailabilityService(db).public_day(op.slug, cal.slug, DAY)
    assert [slot.start_at for slot in response.slots] == [_at(9), _at(14, 45)]
    assert response.slots[1].end_at == _at(17, 45)
    assert all(slot.available for slot in response.slots)


# --- Push management through the configuration service ---------------------


def _write(day: date, hour: int, minute: int = 0) -> PushedSlotWrite:
    return PushedSlotWrite(day=day, start_time=time(hour, minute))


def test_push_slots_converts_local_time_and_lists_with_end(db) -> None:
    op, cal = _setup(db, duration=90)
    db.commit()
    rows = ConfigurationService(db, op.id).push_slots(
        cal.id, PushedSlotsCreate(slots=[_write(DAY, 10)])
    )
    assert len(rows) == 1
    assert rows[0]["start_at"] == _at(10)
    assert rows[0]["end_at"] == _at(11, 30)


def test_push_slots_rejects_duplicates(db) -> None:
    op, cal = _setup(db)
    db.commit()
    service = ConfigurationService(db, op.id)
    service.push_slots(cal.id, PushedSlotsCreate(slots=[_write(DAY, 10)]))
    with pytest.raises(ConflictError):
        service.push_slots(cal.id, PushedSlotsCreate(slots=[_write(DAY, 10)]))


def test_push_slots_rejects_past_and_nonexistent_times(db) -> None:
    op, cal = _setup(db)
    db.commit()
    service = ConfigurationService(db, op.id)
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
    with pytest.raises(ConflictError):
        service.push_slots(cal.id, PushedSlotsCreate(slots=[_write(yesterday, 10)]))
    with pytest.raises(ConflictError):  # 02:30 is skipped by the 2027 spring-forward
        service.push_slots(cal.id, PushedSlotsCreate(slots=[_write(date(2027, 3, 14), 2, 30)]))


def test_dashboard_shows_open_pushed_slot_without_bookings(db) -> None:
    op, cal = _setup(db)
    _push(db, cal, _at(9))
    db.commit()
    slots = BookingAdminService(db, op.id).slots(_at(0), _at(23))
    pushed_entries = [
        entry for slot in slots for entry in slot["calendars"] if entry["pushed"]
    ]
    assert len(pushed_entries) == 1
    entry = pushed_entries[0]
    assert entry["pushed"] is True
    assert entry["bookings"] == []
    assert entry["end_at"] == _at(12)
