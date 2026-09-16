from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def require_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {name}") from exc


def local_datetime(day: date, at: time, timezone_name: str) -> datetime:
    return datetime.combine(day, at, tzinfo=require_timezone(timezone_name))


def wall_time_exists(value: datetime) -> bool:
    """False for a wall time skipped by a DST jump (e.g. 02:30 on spring-forward)."""
    round_trip = value.astimezone(UTC).astimezone(value.tzinfo)
    return round_trip.replace(tzinfo=None) == value.replace(tzinfo=None)

