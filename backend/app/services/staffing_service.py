from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import Booking, Calendar, Operator, Staff, StaffAssignment, StaffHour
from app.utils.timezone import require_timezone


CAPTAIN_ROLE = "captain"


def fits_weekly_hours(
    hours: list[tuple[int, time, time]], local_start: datetime, local_end: datetime
) -> bool:
    if local_start.date() != local_end.date():
        return False
    weekday, start, end = local_start.weekday(), local_start.time(), local_end.time()
    return any(
        day == weekday and opens <= start and end <= closes
        for day, opens, closes in hours
    )


@dataclass(frozen=True, slots=True)
class StaffingReadiness:
    """Authoritative local staffing result for one booking interval."""

    ready: bool
    captain_name: str | None = None
    reason: str | None = None
    assignment_id: uuid.UUID | None = None


def is_captain(role: str | None) -> bool:
    return bool(role and role.strip().casefold() == CAPTAIN_ROLE)


def lock_calendar(db: Session, operator_id: uuid.UUID, calendar_id: uuid.UUID) -> Calendar:
    """Lock the tenant-owned calendar row used to serialize staffing and bookings."""
    calendar = db.scalar(
        select(Calendar)
        .where(
            Calendar.id == calendar_id,
            Calendar.operator_id == operator_id,
            Calendar.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if calendar is None:
        raise NotFoundError("Calendar not found")
    return calendar


def lock_calendars(
    db: Session, operator_id: uuid.UUID, calendar_ids: set[uuid.UUID] | list[uuid.UUID]
) -> dict[uuid.UUID, Calendar]:
    """Lock calendar rows in stable order before staffing or booking writes."""
    ordered_ids = sorted(set(calendar_ids), key=str)
    if not ordered_ids:
        return {}
    rows = list(
        db.scalars(
            select(Calendar)
            .where(
                Calendar.operator_id == operator_id,
                Calendar.id.in_(ordered_ids),
                Calendar.deleted_at.is_(None),
            )
            .order_by(Calendar.id)
            .with_for_update()
        )
    )
    calendars = {calendar.id: calendar for calendar in rows}
    if len(calendars) != len(ordered_ids):
        raise NotFoundError("Calendar not found")
    return calendars


def _operator_zone(db: Session, operator_id: uuid.UUID):
    timezone_name = db.scalar(select(Operator.time_zone).where(Operator.id == operator_id))
    return require_timezone(timezone_name or "UTC")


def _hours_cover_interval(
    db: Session, staff_id: uuid.UUID, start_at: datetime, end_at: datetime, zone: Any
) -> bool:
    if start_at.tzinfo is None or end_at.tzinfo is None:
        return False
    rows = db.execute(
        select(StaffHour.day_of_week, StaffHour.start_time, StaffHour.end_time).where(
            StaffHour.staff_id == staff_id
        )
    )
    weekly = [(day, opens, closes) for day, opens, closes in rows]
    return fits_weekly_hours(weekly, start_at.astimezone(zone), end_at.astimezone(zone))


def readiness_for_interval(
    db: Session,
    operator_id: uuid.UUID,
    calendar_id: uuid.UUID,
    start_at: datetime,
    end_at: datetime,
    *,
    exclude_assignment_id: uuid.UUID | None = None,
) -> StaffingReadiness:
    """Return whether exactly one current local Captain covers the whole interval.

    This deliberately does not require a GHL user or GHL permission verification:
    local scheduling is the source of truth, while GHL identity is only needed for
    remote appointment ownership.
    """
    if start_at.tzinfo is None or end_at.tzinfo is None or start_at >= end_at:
        return StaffingReadiness(False, reason="A valid timezone-aware booking interval is required")

    conditions = [
        StaffAssignment.operator_id == operator_id,
        StaffAssignment.calendar_id == calendar_id,
        StaffAssignment.start_at <= start_at,
        StaffAssignment.end_at >= end_at,
        func.lower(func.trim(StaffAssignment.role)) == CAPTAIN_ROLE,
    ]
    if exclude_assignment_id is not None:
        conditions.append(StaffAssignment.id != exclude_assignment_id)
    rows = list(
        db.execute(
            select(StaffAssignment, Staff)
            .join(Staff, Staff.id == StaffAssignment.staff_id)
            .where(*conditions, Staff.operator_id == operator_id)
            .order_by(StaffAssignment.id)
        )
    )
    if not rows:
        return StaffingReadiness(False, reason="Exactly one active Captain must cover the entire booking")

    zone = _operator_zone(db, operator_id)
    valid: list[tuple[StaffAssignment, Staff]] = []
    invalid_reasons: list[str] = []
    for assignment, staff in rows:
        if staff.deleted_at is not None or not staff.is_active:
            invalid_reasons.append(f"{staff.name} is inactive")
            continue
        if not _hours_cover_interval(db, staff.id, start_at, end_at, zone):
            invalid_reasons.append(f"{staff.name} is not working at that time")
            continue
        valid.append((assignment, staff))

    if len(valid) != 1:
        if len(valid) > 1:
            return StaffingReadiness(False, reason="Only one Captain may cover a booking interval")
        return StaffingReadiness(
            False,
            reason=invalid_reasons[0]
            if invalid_reasons
            else "Exactly one active Captain must cover the entire booking",
        )
    assignment, staff = valid[0]
    return StaffingReadiness(
        True, captain_name=staff.name, assignment_id=assignment.id
    )


def readiness_for_booking(db: Session, booking: Booking) -> StaffingReadiness:
    return readiness_for_interval(
        db,
        booking.operator_id,
        booking.calendar_id,
        booking.start_at,
        booking.end_at,
    )


def ensure_ready_for_booking(
    db: Session,
    operator_id: uuid.UUID,
    calendar_id: uuid.UUID,
    start_at: datetime,
    end_at: datetime,
) -> StaffingReadiness:
    result = readiness_for_interval(db, operator_id, calendar_id, start_at, end_at)
    if not result.ready:
        raise ConflictError(result.reason or "A Captain must be assigned before booking")
    return result


def ensure_no_overlapping_captain(
    db: Session,
    operator_id: uuid.UUID,
    calendar_id: uuid.UUID,
    start_at: datetime,
    end_at: datetime,
    *,
    exclude_assignment_id: uuid.UUID | None = None,
) -> None:
    """Reject a second overlapping Captain on the same calendar."""
    conditions = [
        StaffAssignment.operator_id == operator_id,
        StaffAssignment.calendar_id == calendar_id,
        StaffAssignment.start_at < end_at,
        StaffAssignment.end_at > start_at,
        func.lower(func.trim(StaffAssignment.role)) == CAPTAIN_ROLE,
    ]
    if exclude_assignment_id is not None:
        conditions.append(StaffAssignment.id != exclude_assignment_id)
    if db.scalar(select(StaffAssignment.id).where(*conditions).limit(1)) is not None:
        raise ConflictError("Only one Captain may cover a calendar interval")


__all__ = [
    "CAPTAIN_ROLE",
    "StaffingReadiness",
    "ensure_no_overlapping_captain",
    "ensure_ready_for_booking",
    "is_captain",
    "lock_calendar",
    "lock_calendars",
    "readiness_for_booking",
    "readiness_for_interval",
]
