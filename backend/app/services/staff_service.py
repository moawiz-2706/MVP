import uuid
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import (
    Booking,
    Calendar,
    DepartureLocation,
    GHLCalendarMapping,
    Operator,
    OutboxJob,
    Staff,
    StaffAssignment,
    StaffHour,
)
from app.schemas.staff import (
    StaffAssignmentCreate,
    StaffAssignmentUpdate,
    StaffCreate,
    StaffHourWrite,
    StaffRoleUpdate,
    StaffUpdate,
)
from app.services.outbox_service import OutboxService
from app.services.staffing_service import _staff_covers_interval
from app.utils.timezone import require_timezone


WeeklyHours = list[tuple[int, time, time]]


def fits_weekly_hours(hours: WeeklyHours, local_start: datetime, local_end: datetime) -> bool:
    """True when [local_start, local_end) sits inside one working interval that day.

    Times are operator-local. Like calendar hours, a shift cannot span midnight,
    so a slot crossing into the next day never fits.
    """
    if local_start.date() != local_end.date():
        return False
    weekday, start, end = local_start.weekday(), local_start.time(), local_end.time()
    return any(
        day == weekday and opens <= start and end <= closes for day, opens, closes in hours
    )


class StaffService:
    """Staff CRUD plus assignment of staff to calendar time slots.

    A staff member is busy for the whole slot they are assigned to, across every
    calendar. Assignment locks the staff row FOR UPDATE before checking for
    overlaps, so two concurrent assignments of the same person serialize and
    the second one sees the first.
    """

    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id

    def _zone(self):
        return require_timezone(
            self.db.scalar(select(Operator.time_zone).where(Operator.id == self.operator_id))
            or "UTC"
        )

    def _staff_zone(self, staff: Staff):
        return require_timezone(staff.availability_time_zone or str(self._zone()))

    def _staff(self, staff_id: uuid.UUID, *, lock: bool = False) -> Staff:
        statement = select(Staff).where(
            Staff.id == staff_id,
            Staff.operator_id == self.operator_id,
            Staff.deleted_at.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        staff = self.db.scalar(statement)
        if staff is None:
            raise NotFoundError("Staff member not found")
        return staff

    def _hours(self, staff_ids: list[uuid.UUID]) -> dict[uuid.UUID, WeeklyHours]:
        grouped: dict[uuid.UUID, WeeklyHours] = defaultdict(list)
        if staff_ids:
            for row in self.db.scalars(
                select(StaffHour)
                .where(StaffHour.staff_id.in_(staff_ids))
                .order_by(StaffHour.day_of_week, StaffHour.start_time)
            ):
                grouped[row.staff_id].append((row.day_of_week, row.start_time, row.end_time))
        return grouped

    @staticmethod
    def _payload(staff: Staff, hours: WeeklyHours, upcoming: int = 0) -> dict[str, Any]:
        return {
            **staff.__dict__,
            "hours": [
                {"day_of_week": day, "start_time": opens, "end_time": closes}
                for day, opens, closes in hours
            ],
            "upcoming_assignments": upcoming,
        }

    def _replace_hours(self, staff_id: uuid.UUID, hours: list[StaffHourWrite]) -> None:
        self.db.execute(delete(StaffHour).where(StaffHour.staff_id == staff_id))
        self.db.add_all([StaffHour(staff_id=staff_id, **item.model_dump()) for item in hours])

    # --- Staff CRUD -----------------------------------------------------------

    def list_staff(self) -> list[dict[str, Any]]:
        staff = list(
            self.db.scalars(
                select(Staff)
                .where(Staff.operator_id == self.operator_id, Staff.deleted_at.is_(None))
                .order_by(Staff.name)
            )
        )
        ids = [member.id for member in staff]
        hours = self._hours(ids)
        upcoming = dict(
            self.db.execute(
                select(StaffAssignment.staff_id, func.count(StaffAssignment.id))
                .where(
                    StaffAssignment.staff_id.in_(ids),
                    StaffAssignment.end_at > datetime.now(UTC),
                )
                .group_by(StaffAssignment.staff_id)
            ).all()
        ) if ids else {}
        return [self._payload(m, hours.get(m.id, []), upcoming.get(m.id, 0)) for m in staff]

    def get_staff(self, staff_id: uuid.UUID) -> dict[str, Any]:
        staff = self._staff(staff_id)
        return self._payload(staff, self._hours([staff.id]).get(staff.id, []))

    def update_custom_role(self, staff_id: uuid.UUID, data: StaffRoleUpdate) -> dict[str, Any]:
        staff = self._staff(staff_id, lock=True)
        staff.custom_role = data.custom_role
        calendar_ids = set(
            self.db.scalars(
                select(StaffAssignment.calendar_id).where(
                    StaffAssignment.staff_id == staff.id,
                    StaffAssignment.end_at > datetime.now(UTC),
                )
            )
        )
        self.db.commit()
        self._queue_appointment_sync_for_calendars(calendar_ids)
        return self.get_staff(staff.id)

    def _queue_job(self, job_type: str, key: str, payload: dict[str, Any]) -> None:
        """Queue a HighLevel side effect in the same transaction as the change."""
        self.db.add(
            OutboxJob(
                operator_id=self.operator_id,
                job_type=job_type,
                idempotency_key=key,
                payload=payload,
                status="pending",
            )
        )

    def _queue_calendar_sync(self, calendar_id: uuid.UUID) -> None:
        if not get_settings().ghl_calendar_sync_enabled:
            return
        mapping = self.db.scalar(
            select(GHLCalendarMapping).where(
                GHLCalendarMapping.operator_id == self.operator_id,
                GHLCalendarMapping.calendar_id == calendar_id,
            )
        )
        if mapping is None:
            mapping = GHLCalendarMapping(
                operator_id=self.operator_id,
                calendar_id=calendar_id,
                desired_revision=1,
                status="pending",
            )
            self.db.add(mapping)
        else:
            mapping.desired_revision += 1
            mapping.status = "pending"
        self._queue_job(
            "ghl_sync_calendar",
            f"calendar:{calendar_id}:revision:{mapping.desired_revision}",
            {"calendar_id": str(calendar_id)},
        )
        self.db.commit()
        try:
            OutboxService(self.db, get_settings()).process(limit=5)
        except Exception:
            # The change is committed; the scheduled worker can retry the job.
            pass

    def _queue_appointment_sync_for_calendars(self, calendar_ids: set[uuid.UUID]) -> None:
        if not get_settings().ghl_calendar_sync_enabled or not calendar_ids:
            return
        bookings = self.db.scalars(
            select(Booking).where(
                Booking.operator_id == self.operator_id,
                Booking.calendar_id.in_(calendar_ids),
                Booking.status.not_in(("cancelled", "failed")),
                Booking.end_at > datetime.now(UTC),
            )
        )
        for booking in bookings:
            self._queue_job(
                "ghl_sync_appointment",
                f"booking:{booking.id}:ghl_appointment:staff:{uuid.uuid4().hex}",
                {
                    "booking_id": str(booking.id),
                    "booking_order_id": str(booking.booking_order_id),
                },
            )
        self.db.commit()
        try:
            OutboxService(self.db, get_settings()).process(limit=100, prefer_newest=True)
        except Exception:
            # The local staff change is committed; appointment jobs retry through
            # the durable outbox if HighLevel is unavailable.
            pass

    def _queue_contact_sync(self, staff: Staff) -> None:
        # Every profile change gets its own job so the latest details are pushed.
        self._queue_job(
            "ghl_upsert_staff_contact",
            f"staff:{staff.id}:ghl_contact:{uuid.uuid4().hex}",
            {"staff_id": str(staff.id)},
        )

    def _queue_staff_user_sync(self, staff: Staff, *, manual_review: bool = False) -> None:
        if not get_settings().ghl_staff_user_sync_enabled:
            return
        if manual_review:
            staff.ghl_user_sync_status = "manual_review"
        self._queue_job(
            "ghl_sync_staff_user",
            f"staff:{staff.id}:ghl_user:{uuid.uuid4().hex}",
            {"staff_id": str(staff.id), "manual_review": manual_review},
        )

    def create_staff(self, data: StaffCreate) -> dict[str, Any]:
        staff = Staff(operator_id=self.operator_id, **data.model_dump(exclude={"hours"}))
        self.db.add(staff)
        self.db.flush()
        self._replace_hours(staff.id, data.hours)
        if staff.email:
            self._queue_contact_sync(staff)
        self._queue_staff_user_sync(staff)
        self.db.commit()
        return self.get_staff(staff.id)

    def update_staff(self, staff_id: uuid.UUID, data: StaffUpdate) -> dict[str, Any]:
        staff = self._staff(staff_id)
        values = data.model_dump(exclude_unset=True, exclude={"hours"})
        calendar_ids: set[uuid.UUID] = set()
        contact_changed = any(
            key in values and values[key] != getattr(staff, key) for key in ("name", "email", "phone")
        )
        if values.get("name") != staff.name and "name" in values:
            calendar_ids.update(
                self.db.scalars(
                    select(StaffAssignment.calendar_id).where(
                        StaffAssignment.staff_id == staff.id,
                        StaffAssignment.end_at > datetime.now(UTC),
                    )
                )
            )
        for key, value in values.items():
            setattr(staff, key, value)
        if values.get("is_active") is False:
            from app.services.staffing_service import lock_calendars
            calendar_ids.update(
                self.db.scalars(
                    select(StaffAssignment.calendar_id).where(
                        StaffAssignment.staff_id == staff.id,
                        StaffAssignment.end_at > datetime.now(UTC),
                    )
                )
            )
            lock_calendars(self.db, self.operator_id, calendar_ids)
            self.db.execute(
                delete(StaffAssignment).where(
                    StaffAssignment.staff_id == staff.id,
                    StaffAssignment.end_at > datetime.now(UTC),
                )
            )
        if contact_changed and staff.email:
            self._queue_contact_sync(staff)
        if values or data.hours is not None:
            self._queue_staff_user_sync(staff, manual_review=values.get("is_active") is False)
        # Existing assignments are kept even if new hours no longer cover them;
        # hours gate new assignments only.
        if data.hours is not None:
            self._replace_hours(staff.id, data.hours)
        self.db.commit()
        for calendar_id in calendar_ids:
            self._queue_calendar_sync(calendar_id)
        self._queue_appointment_sync_for_calendars(calendar_ids)
        return self.get_staff(staff.id)

    def delete_staff(self, staff_id: uuid.UUID) -> None:
        """Soft-delete. Upcoming assignments are released; past ones stay as history."""
        staff = self._staff(staff_id, lock=True)
        now = datetime.now(UTC)
        calendar_ids = set(
            self.db.scalars(
                select(StaffAssignment.calendar_id).where(
                    StaffAssignment.staff_id == staff.id,
                    StaffAssignment.end_at > now,
                )
            )
        )
        from app.services.staffing_service import lock_calendars
        lock_calendars(self.db, self.operator_id, calendar_ids)
        staff.deleted_at = now
        staff.is_active = False
        self._queue_staff_user_sync(staff, manual_review=True)
        self.db.execute(
            delete(StaffAssignment).where(
                StaffAssignment.staff_id == staff.id, StaffAssignment.end_at > now
            )
        )
        self.db.commit()
        for calendar_id in calendar_ids:
            self._queue_calendar_sync(calendar_id)
        self._queue_appointment_sync_for_calendars(calendar_ids)

    # --- Assignments ----------------------------------------------------------

    def _calendar(self, calendar_id: uuid.UUID) -> Calendar:
        calendar = self.db.scalar(
            select(Calendar).where(
                Calendar.id == calendar_id,
                Calendar.operator_id == self.operator_id,
                Calendar.deleted_at.is_(None),
                Calendar.is_active.is_(True),
            )
        )
        if calendar is None:
            raise NotFoundError("Calendar not found")
        return calendar

    def _overlaps(
        self, staff_ids: list[uuid.UUID], start_at: datetime, end_at: datetime
    ) -> dict[uuid.UUID, tuple[StaffAssignment, str]]:
        """First overlapping assignment per staff member (touching ends do not overlap)."""
        found: dict[uuid.UUID, tuple[StaffAssignment, str]] = {}
        if not staff_ids:
            return found
        rows = self.db.execute(
            select(StaffAssignment, Calendar.name)
            .join(Calendar, Calendar.id == StaffAssignment.calendar_id)
            .where(
                StaffAssignment.staff_id.in_(staff_ids),
                StaffAssignment.start_at < end_at,
                StaffAssignment.end_at > start_at,
            )
            .order_by(StaffAssignment.start_at)
        )
        for assignment, calendar_name in rows:
            found.setdefault(assignment.staff_id, (assignment, calendar_name))
        return found

    def _unavailable_reason(
        self,
        staff: Staff,
        hours: WeeklyHours,
        overlap: tuple[StaffAssignment, str] | None,
        start_at: datetime,
        end_at: datetime,
        zone,
    ) -> str | None:
        if not staff.is_active:
            return f"{staff.name} is inactive"
        if overlap is not None:
            assignment, calendar_name = overlap
            busy_from = assignment.start_at.astimezone(zone)
            busy_to = assignment.end_at.astimezone(zone)
            return (
                f"{staff.name} is already assigned to {calendar_name} "
                f"({busy_from:%b %d, %H:%M}–{busy_to:%H:%M})"
            )
        if not _staff_covers_interval(self.db, staff, start_at, end_at):
            return f"{staff.name} is not working at that time"
        return None

    @staticmethod
    def _assignment_payload(assignment: StaffAssignment, staff_name: str) -> dict[str, Any]:
        return {
            "id": assignment.id,
            "staff_id": assignment.staff_id,
            "staff_name": staff_name,
            "calendar_id": assignment.calendar_id,
            "start_at": assignment.start_at,
            "end_at": assignment.end_at,
            "role": assignment.role,
        }

    def list_assignments(
        self,
        range_start: datetime,
        range_end: datetime,
        *,
        calendar_id: uuid.UUID | None = None,
        staff_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        if range_start.tzinfo is None or range_end.tzinfo is None or range_start >= range_end:
            raise ValueError("A valid timezone-aware range is required")
        if range_end - range_start > timedelta(days=93):
            raise ValueError("Assignment query range cannot exceed 93 days")
        conditions = [
            StaffAssignment.operator_id == self.operator_id,
            StaffAssignment.start_at < range_end,
            StaffAssignment.end_at > range_start,
        ]
        if calendar_id:
            conditions.append(StaffAssignment.calendar_id == calendar_id)
        if staff_id:
            conditions.append(StaffAssignment.staff_id == staff_id)
        rows = self.db.execute(
            select(StaffAssignment, Staff.name)
            .join(Staff, Staff.id == StaffAssignment.staff_id)
            .join(Calendar, Calendar.id == StaffAssignment.calendar_id)
            .where(*conditions)
            .where(Calendar.deleted_at.is_(None))
            .order_by(StaffAssignment.start_at, Staff.name)
        )
        return [self._assignment_payload(assignment, name) for assignment, name in rows]

    def candidates(
        self, calendar_id: uuid.UUID, start_at: datetime, required_role: str | None = None
    ) -> list[dict[str, Any]]:
        """Active staff matching a Passport custom role, flagged by availability."""
        calendar = self._calendar(calendar_id)
        end_at = start_at + timedelta(minutes=calendar.duration_minutes)
        normalized_role = (required_role or "").strip().casefold() or None
        staff = list(
            self.db.scalars(
                select(Staff)
                .where(
                    Staff.operator_id == self.operator_id,
                    Staff.deleted_at.is_(None),
                    Staff.is_active.is_(True),
                    *(
                        [func.lower(Staff.custom_role) == normalized_role]
                        if normalized_role
                        else []
                    ),
                )
                .order_by(Staff.name)
            )
        )
        ids = [member.id for member in staff]
        hours, overlaps = self._hours(ids), self._overlaps(ids, start_at, end_at)
        zone = self._zone()
        result = []
        for member in staff:
            reason = self._unavailable_reason(
                member,
                hours.get(member.id, []),
                overlaps.get(member.id),
                start_at,
                end_at,
                self._staff_zone(member),
            )
            result.append(
                {
                    "staff_id": member.id,
                    "name": member.name,
                    "custom_role": member.custom_role,
                    "available": reason is None,
                    "reason": reason,
                }
            )
        return result

    def assign(self, data: StaffAssignmentCreate) -> dict[str, Any]:
        from app.services.staffing_service import ensure_no_overlapping_captain, lock_calendar, is_captain

        calendar = lock_calendar(self.db, self.operator_id, data.calendar_id)
        end_at = data.start_at + timedelta(minutes=calendar.duration_minutes)
        staff = self._staff(data.staff_id, lock=True)
        if not staff.custom_role:
            raise ConflictError(f"{staff.name} must be assigned a custom role on the Staff page first")
        if data.role and staff.custom_role.casefold() != data.role.strip().casefold():
            raise ConflictError(f"{staff.name} is assigned the {staff.custom_role} role, not {data.role}")
        assignment_role = data.role or staff.custom_role
        if is_captain(assignment_role):
            ensure_no_overlapping_captain(
                self.db, self.operator_id, calendar.id, data.start_at, end_at
            )
        reason = self._unavailable_reason(
            staff,
            self._hours([staff.id]).get(staff.id, []),
            self._overlaps([staff.id], data.start_at, end_at).get(staff.id),
            data.start_at,
            end_at,
            self._staff_zone(staff),
        )
        if reason:
            raise ConflictError(reason)
        assignment = StaffAssignment(
            operator_id=self.operator_id,
            staff_id=staff.id,
            calendar_id=calendar.id,
            start_at=data.start_at,
            end_at=end_at,
            role=assignment_role,
        )
        self.db.add(assignment)
        self.db.flush()
        if staff.email and assignment.start_at > datetime.now(UTC):
            self._queue_job(
                "ghl_staff_assigned_email",
                f"assignment:{assignment.id}:assigned",
                {"assignment_id": str(assignment.id)},
            )
        self.db.commit()
        self._queue_calendar_sync(calendar.id)
        self._queue_appointment_sync_for_calendars({calendar.id})
        return self._assignment_payload(assignment, staff.name)

    def _assignment(self, assignment_id: uuid.UUID) -> tuple[StaffAssignment, str]:
        row = self.db.execute(
            select(StaffAssignment, Staff.name)
            .join(Staff, Staff.id == StaffAssignment.staff_id)
            .where(
                StaffAssignment.id == assignment_id,
                StaffAssignment.operator_id == self.operator_id,
            )
        ).one_or_none()
        if row is None:
            raise NotFoundError("Assignment not found")
        return row

    def update_assignment(
        self, assignment_id: uuid.UUID, data: StaffAssignmentUpdate
    ) -> dict[str, Any]:
        from app.services.staffing_service import ensure_no_overlapping_captain, is_captain, lock_calendar

        assignment, _ = self._assignment(assignment_id)
        calendar = lock_calendar(self.db, self.operator_id, assignment.calendar_id)
        current_staff = self._staff(assignment.staff_id, lock=True)
        target_staff = (
            current_staff
            if data.staff_id is None or data.staff_id == current_staff.id
            else self._staff(data.staff_id, lock=True)
        )
        role = data.role if "role" in data.model_fields_set else assignment.role
        if not target_staff.custom_role:
            raise ConflictError(f"{target_staff.name} must be assigned a custom role on the Staff page first")
        if role and target_staff.custom_role.casefold() != role.strip().casefold():
            raise ConflictError(f"{target_staff.name} is assigned the {target_staff.custom_role} role, not {role}")
        role = role or target_staff.custom_role
        overlap = None
        if target_staff.id != assignment.staff_id:
            overlap = self._overlaps([target_staff.id], assignment.start_at, assignment.end_at).get(target_staff.id)
        reason = self._unavailable_reason(
            target_staff,
            self._hours([target_staff.id]).get(target_staff.id, []),
            overlap,
            assignment.start_at,
            assignment.end_at,
            self._staff_zone(target_staff),
        )
        if reason:
            raise ConflictError(reason)
        if is_captain(role):
            ensure_no_overlapping_captain(
                self.db, self.operator_id, calendar.id, assignment.start_at, assignment.end_at,
                exclude_assignment_id=assignment.id,
            )
        assignment.staff_id = target_staff.id
        assignment.role = role
        self.db.commit()
        self._queue_calendar_sync(calendar.id)
        self._queue_appointment_sync_for_calendars({calendar.id})
        return self._assignment_payload(assignment, target_staff.name)

    def unassign(self, assignment_id: uuid.UUID) -> None:
        """Remove staff from a slot and, for an upcoming slot, email them about it."""
        assignment, _ = self._assignment(assignment_id)
        from app.services.staffing_service import lock_calendar
        lock_calendar(self.db, self.operator_id, assignment.calendar_id)
        staff = self.db.get(Staff, assignment.staff_id)
        if staff and staff.email and staff.deleted_at is None and assignment.start_at > datetime.now(UTC):
            calendar = self.db.get(Calendar, assignment.calendar_id)
            location = (
                self.db.get(DepartureLocation, calendar.departure_location_id)
                if calendar and calendar.departure_location_id
                else None
            )
            # The assignment row is deleted below, so the email works from this snapshot.
            self._queue_job(
                "ghl_staff_unassigned_email",
                f"assignment:{assignment.id}:unassigned",
                {
                    "staff_id": str(staff.id),
                    "calendar_name": calendar.name if calendar else "your scheduled activity",
                    "start_at": assignment.start_at.isoformat(),
                    "end_at": assignment.end_at.isoformat(),
                    "role": assignment.role,
                    "location_name": location.name if location else None,
                    "location_address": location.address if location else None,
                },
            )
        self.db.delete(assignment)
        self.db.commit()
        self._queue_calendar_sync(assignment.calendar_id)
        self._queue_appointment_sync_for_calendars({assignment.calendar_id})
