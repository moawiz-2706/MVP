from datetime import date, time, timedelta

import pytest

from app.utils.timezone import local_datetime, require_timezone


def test_require_timezone_rejects_unknown_zone() -> None:
    with pytest.raises(ValueError, match="Unknown IANA timezone"):
        require_timezone("Mars/Olympus_Mons")


def test_local_datetime_is_zone_aware() -> None:
    value = local_datetime(date(2027, 6, 10), time(9, 0), "America/New_York")
    assert value.tzinfo is not None
    assert value.hour == 9


def test_spec42_dst_offsets_differ_across_the_year() -> None:
    # Same wall-clock hour resolves to different UTC instants across the DST
    # boundary; fixed offsets are never assumed.
    winter = local_datetime(date(2027, 1, 10), time(9, 0), "America/New_York")
    summer = local_datetime(date(2027, 7, 10), time(9, 0), "America/New_York")
    assert winter.utcoffset() == timedelta(hours=-5)  # EST
    assert summer.utcoffset() == timedelta(hours=-4)  # EDT
    # 09:00 local is a different absolute time in each season.
    assert winter.astimezone(require_timezone("UTC")).hour == 14
    assert summer.astimezone(require_timezone("UTC")).hour == 13


def test_spec40_booking_must_fit_completely_inside_hours() -> None:
    # Hours 08:00-17:00, duration 180 => latest valid start is 14:00.
    day, zone = date(2027, 6, 10), "America/New_York"
    opening = local_datetime(day, time(8, 0), zone)
    closing = local_datetime(day, time(17, 0), zone)
    duration = timedelta(minutes=180)

    def fits(start_hour: int) -> bool:
        start = local_datetime(day, time(start_hour, 0), zone)
        return start >= opening and start + duration <= closing

    assert fits(14)  # 14:00 -> 17:00, exactly to close, valid
    assert not fits(16)  # 16:00 -> 19:00, past close, invalid
