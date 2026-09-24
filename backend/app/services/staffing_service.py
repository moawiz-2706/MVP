from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import (
    Booking,
    Calendar,
    Staff,
    StaffAssignment,
    StaffAvailabilityWindow,
    StaffHour,
)
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


def _staff_covers_interval(
    db: Session, staff: Staff, start_at: datetime, end_at: datetime
) -> bool:
    """Check concrete GHL windows, with a pre-sync compatibility fallback."""
    windows = list(
        db.execute(
            select(StaffAvailabilityWindow.start_at, StaffAvailabilityWindow.end_at).where(
                StaffAvailabilityWindow.staff_id == staff.id,
                StaffAvailabilityWindow.start_at < end_at,
                StaffAvailabilityWindow.end_at > start_at,
            )
        )
    )
    if windows:
        return any(window_start <= start_at and window_end >= end_at for window_start, window_end in windows)
    if staff.availability_sync_status == "synced":
        return False
    zone = require_timezone(staff.availability_time_zone or "UTC")
    return _hours_cover_interval(db, staff.id, start_at, end_at, zone)


def pool_readiness_for_interval(
    db: Session,
    operator_id: uuid.UUID,
    calendar_id: uuid.UUID,
    start_at: datetime,
    end_at: datetime,
) -> StaffingReadiness:
    """Return whether every configured role pool has at least one available person."""
    calendar = db.scalar(
        select(Calendar).where(
            Calendar.id == calendar_id,
            Calendar.operator_id == operator_id,
            Calendar.deleted_at.is_(None),
        )
    )
    if calendar is None:
        return StaffingReadiness(False, reason="Calendar not found")
    roles = [str(role).strip() for role in (calendar.required_staff_roles or ["Captain"]) if str(role).strip()]
    staff = list(
        db.scalars(
            select(Staff).where(
                Staff.operator_id == operator_id,
                Staff.deleted_at.is_(None),
                Staff.is_active.is_(True),
                func.lower(Staff.custom_role).in_([role.casefold() for role in roles]),
            )
        )
    )
    for role in roles:
        matches = [member for member in staff if (member.custom_role or "").casefold() == role.casefold()]
        if not any(_staff_covers_interval(db, member, start_at, end_at) for member in matches):
            return StaffingReadiness(False, reason=f"No available {role} is scheduled for this time")
    return StaffingReadiness(True)


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

    calendar = db.scalar(
        select(Calendar).where(
            Calendar.id == calendar_id,
            Calendar.operator_id == operator_id,
            Calendar.deleted_at.is_(None),
        )
    )
    roles = [str(role).strip() for role in ((calendar.required_staff_roles if calendar else None) or ["Captain"]) if str(role).strip()]
    conditions = [
        StaffAssignment.operator_id == operator_id,
        StaffAssignment.calendar_id == calendar_id,
        StaffAssignment.start_at <= start_at,
        StaffAssignment.end_at >= end_at,
        func.lower(func.trim(StaffAssignment.role)).in_([role.casefold() for role in roles]),
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
    valid_by_role: dict[str, list[tuple[StaffAssignment, Staff]]] = {role.casefold(): [] for role in roles}
    invalid_reasons: list[str] = []
    for assignment, staff in rows:
        if staff.deleted_at is not None or not staff.is_active:
            invalid_reasons.append(f"{staff.name} is inactive")
            continue
        if not _staff_covers_interval(db, staff, start_at, end_at):
            invalid_reasons.append(f"{staff.name} is not working at that time")
            continue
        valid_by_role.setdefault((assignment.role or "").casefold(), []).append((assignment, staff))
    for role in roles:
        valid = valid_by_role.get(role.casefold(), [])
        if not valid:
            return StaffingReadiness(
                False,
                reason=invalid_reasons[0] if invalid_reasons else f"A {role} must be assigned before booking",
            )
        if is_captain(role) and len(valid) > 1:
            return StaffingReadiness(False, reason="Only one Captain may cover a booking interval")
    captain = valid_by_role.get(CAPTAIN_ROLE, [])
    assignment, staff = captain[0] if captain else (None, None)
    return StaffingReadiness(
        True,
        captain_name=staff.name if staff else None,
        assignment_id=assignment.id if assignment else None,
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
    "pool_readiness_for_interval",
    "readiness_for_booking",
    "readiness_for_interval",
]
