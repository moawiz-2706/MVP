"""DB-backed tests for the two exclusive availability modes.

day_wise  -> recurring weekly calendar_hours
date_wise -> explicit calendar_date_hours ranges

Exactly one mode governs a calendar; the inactive mode's rows must be ignored.
Gated on TEST_DATABASE_URL (see conftest).
"""

import os
import uuid
from datetime import date, time

import pytest

from app.models.entities import (
    Calendar,
    CalendarDateHour,
    CalendarHour,
    Operator,
    Staff,
    StaffAssignment,
    StaffHour,
)
from app.services.availability_service import AvailabilityService
from app.utils.timezone import local_datetime

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)

TZ = "America/New_York"
IN_RANGE = date(2027, 6, 15)   # Tuesday, inside the June range
OUT_OF_RANGE = date(2027, 7, 15)  # Thursday, outside every range


def _operator(db) -> Operator:
    op = Operator(
        ghl_location_id=f"loc-{uuid.uuid4()}",
        name="Punta Gorda Rentals",
        slug=f"op-{uuid.uuid4().hex[:8]}",
        time_zone=TZ,
    )
    db.add(op)
    db.flush()
    return op


def _calendar(db, op, *, mode: str) -> Calendar:
    cal = Calendar(
        operator_id=op.id,
        name="3-Hour Single Kayak Rental",
        slug=f"cal-{uuid.uuid4().hex[:8]}",
        duration_minutes=180,
        slot_interval_minutes=30,
        base_price_minor=7000,
        availability_mode=mode,
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
            start_at=_at(date(2027, 6, 1), 0),
            end_at=_at(date(2027, 8, 1), 0),
            role="Captain",
        )
    )
    db.flush()
    return cal


def _weekly_hours(db, cal) -> None:
    for dow in range(7):
        db.add(CalendarHour(calendar_id=cal.id, day_of_week=dow, start_time=time(8), end_time=time(18)))
    db.flush()


def _date_hours(db, cal, start: date, end: date, opens=time(8), closes=time(18)) -> None:
    db.add(
        CalendarDateHour(
            calendar_id=cal.id, start_date=start, end_date=end, start_time=opens, end_time=closes
        )
    )
    db.flush()


def _at(day: date, hour: int):
    return local_datetime(day, time(hour, 0), TZ)


def test_date_wise_slot_inside_range_is_available(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op, mode="date_wise")
    _date_hours(db, cal, date(2027, 6, 1), date(2027, 6, 30))
    db.commit()
    assert AvailabilityService(db).check(cal.id, _at(IN_RANGE, 10), 1, operator_id=op.id).available


def test_date_wise_slot_outside_every_range_is_unavailable(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op, mode="date_wise")
    _date_hours(db, cal, date(2027, 6, 1), date(2027, 6, 30))
    db.commit()
    result = AvailabilityService(db).check(cal.id, _at(OUT_OF_RANGE, 10), 1, operator_id=op.id)
    assert not result.available


def test_date_wise_ignores_weekly_hours(db) -> None:
    # Weekly hours cover every day, but the calendar is date_wise with no ranges,
    # so nothing is bookable. Proves the modes never combine.
    op = _operator(db)
    cal = _calendar(db, op, mode="date_wise")
    _weekly_hours(db, cal)
    db.commit()
    assert not AvailabilityService(db).check(cal.id, _at(IN_RANGE, 10), 1, operator_id=op.id).available


def test_day_wise_ignores_date_ranges(db) -> None:
    # Inverse: a date range exists but the calendar is day_wise with no weekly rows.
    op = _operator(db)
    cal = _calendar(db, op, mode="day_wise")
    _date_hours(db, cal, date(2027, 6, 1), date(2027, 6, 30))
    db.commit()
    assert not AvailabilityService(db).check(cal.id, _at(IN_RANGE, 10), 1, operator_id=op.id).available


def test_date_wise_respects_time_interval_and_duration(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op, mode="date_wise")
    _date_hours(db, cal, IN_RANGE, IN_RANGE, opens=time(8), closes=time(17))
    db.commit()
    engine = AvailabilityService(db)
    assert engine.check(cal.id, _at(IN_RANGE, 14), 1, operator_id=op.id).available      # 14->17 fits
    assert not engine.check(cal.id, _at(IN_RANGE, 16), 1, operator_id=op.id).available  # 16->19 past close
    assert not engine.check(cal.id, _at(IN_RANGE, 6), 1, operator_id=op.id).available   # before open


def test_date_wise_supports_multiple_intervals_in_one_range(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op, mode="date_wise")
    _date_hours(db, cal, IN_RANGE, IN_RANGE, opens=time(8), closes=time(11))
    _date_hours(db, cal, IN_RANGE, IN_RANGE, opens=time(14), closes=time(18))
    db.commit()
    engine = AvailabilityService(db)
    assert engine.check(cal.id, _at(IN_RANGE, 8), 1, operator_id=op.id).available       # first interval
    assert engine.check(cal.id, _at(IN_RANGE, 15), 1, operator_id=op.id).available      # second interval
    assert not engine.check(cal.id, _at(IN_RANGE, 12), 1, operator_id=op.id).available  # the gap


# --- Blocked dates as whole-day ranges -------------------------------------


def test_block_date_range_round_trips_and_blocks_those_days(db) -> None:
    from app.schemas.configuration import CalendarBlockDateRange, CalendarBlocksReplace
    from app.services.configuration_service import ConfigurationService

    op = _operator(db)
    cal = _calendar(db, op, mode="date_wise")
    _date_hours(db, cal, date(2027, 6, 1), date(2027, 6, 30))
    db.commit()

    service = ConfigurationService(db, op.id)
    service.replace_blocks(
        cal.id,
        CalendarBlocksReplace(
            blocks=[
                CalendarBlockDateRange(
                    start_date=date(2027, 6, 10), end_date=date(2027, 6, 12), reason="Maintenance"
                )
            ]
        ),
    )

    # Dates survive the timestamp conversion exactly (end_date is inclusive).
    rows = service.list_blocks(cal.id)
    assert len(rows) == 1
    assert rows[0]["start_date"] == date(2027, 6, 10)
    assert rows[0]["end_date"] == date(2027, 6, 12)

    engine = AvailabilityService(db)
    # Every day in the range is blocked, including the last one...
    assert not engine.check(cal.id, _at(date(2027, 6, 10), 10), 1, operator_id=op.id).available
    assert not engine.check(cal.id, _at(date(2027, 6, 12), 10), 1, operator_id=op.id).available
    # ...and the day after is not.
    assert engine.check(cal.id, _at(date(2027, 6, 13), 10), 1, operator_id=op.id).available


def test_replace_blocks_replaces_previous_ranges(db) -> None:
    from app.schemas.configuration import CalendarBlockDateRange, CalendarBlocksReplace
    from app.services.configuration_service import ConfigurationService

    op = _operator(db)
    cal = _calendar(db, op, mode="date_wise")
    _date_hours(db, cal, date(2027, 6, 1), date(2027, 6, 30))
    db.commit()
    service = ConfigurationService(db, op.id)

    service.replace_blocks(
        cal.id,
        CalendarBlocksReplace(
            blocks=[CalendarBlockDateRange(start_date=date(2027, 6, 10), end_date=date(2027, 6, 12))]
        ),
    )
    service.replace_blocks(
        cal.id,
        CalendarBlocksReplace(
            blocks=[CalendarBlockDateRange(start_date=date(2027, 6, 20), end_date=date(2027, 6, 21))]
        ),
    )
    rows = service.list_blocks(cal.id)
    assert len(rows) == 1
    assert rows[0]["start_date"] == date(2027, 6, 20)
    # The old range is gone, so those days are bookable again.
    assert AvailabilityService(db).check(
        cal.id, _at(date(2027, 6, 10), 10), 1, operator_id=op.id
    ).available
