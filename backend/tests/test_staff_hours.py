"""Pure-logic tests for staff working-hours fit and DST wall-time validation."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.services.staff_service import fits_weekly_hours
from app.utils.timezone import local_datetime, wall_time_exists

NY = ZoneInfo("America/New_York")
TUESDAY = date(2027, 6, 15)
WEDNESDAY = date(2027, 6, 16)
SPLIT_SHIFT = [(1, time(8), time(12)), (1, time(13), time(18))]  # Tuesday 08-12, 13-18


def _at(hour: int, day: date = TUESDAY) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=NY)


def test_slot_inside_first_interval_fits() -> None:
    assert fits_weekly_hours(SPLIT_SHIFT, _at(9), _at(12))  # ends exactly at close


def test_slot_inside_second_interval_fits() -> None:
    assert fits_weekly_hours(SPLIT_SHIFT, _at(13), _at(16))


def test_slot_spanning_the_break_does_not_fit() -> None:
    assert not fits_weekly_hours(SPLIT_SHIFT, _at(11), _at(14))


def test_slot_on_a_day_without_hours_does_not_fit() -> None:
    assert not fits_weekly_hours(SPLIT_SHIFT, _at(9, WEDNESDAY), _at(11, WEDNESDAY))


def test_no_hours_never_fits() -> None:
    assert not fits_weekly_hours([], _at(9), _at(10))


def test_slot_crossing_midnight_never_fits() -> None:
    all_day = [(1, time(0), time(23, 59)), (2, time(0), time(23, 59))]
    assert not fits_weekly_hours(all_day, _at(22), _at(1, WEDNESDAY))


def test_wall_time_exists_rejects_spring_forward_gap() -> None:
    spring_forward = date(2027, 3, 14)
    assert not wall_time_exists(local_datetime(spring_forward, time(2, 30), "America/New_York"))
    assert wall_time_exists(local_datetime(spring_forward, time(3, 30), "America/New_York"))


def test_wall_time_exists_accepts_fall_back_repeat() -> None:
    fall_back = date(2027, 11, 7)
    assert wall_time_exists(local_datetime(fall_back, time(1, 30), "America/New_York"))
