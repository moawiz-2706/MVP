import uuid
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import (
    Calendar,
    DepartureLocation,
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
    StaffUpdate,
)
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

    def _queue_contact_sync(self, staff: Staff) -> None:
        # Every profile change gets its own job so the latest details are pushed.
        self._queue_job(
            "ghl_upsert_staff_contact",
            f"staff:{staff.id}:ghl_contact:{uuid.uuid4().hex}",
            {"staff_id": str(staff.id)},
        )

    def create_staff(self, data: StaffCreate) -> dict[str, Any]:
        staff = Staff(operator_id=self.operator_id, **data.model_dump(exclude={"hours"}))
        self.db.add(staff)
        self.db.flush()
        self._replace_hours(staff.id, data.hours)
        if staff.email:
            self._queue_contact_sync(staff)
        self.db.commit()
        return self.get_staff(staff.id)

    def update_staff(self, staff_id: uuid.UUID, data: StaffUpdate) -> dict[str, Any]:
        staff = self._staff(staff_id)
        values = data.model_dump(exclude_unset=True, exclude={"hours"})
        contact_changed = any(
            key in values and values[key] != getattr(staff, key) for key in ("name", "email", "phone")
        )
        for key, value in values.items():
            setattr(staff, key, value)
        if contact_changed and staff.email:
            self._queue_contact_sync(staff)
        # Existing assignments are kept even if new hours no longer cover them;
        # hours gate new assignments only.
        if data.hours is not None:
            self._replace_hours(staff.id, data.hours)
        self.db.commit()
        return self.get_staff(staff.id)

    def delete_staff(self, staff_id: uuid.UUID) -> None:
        """Soft-delete. Upcoming assignments are released; past ones stay as history."""
        staff = self._staff(staff_id, lock=True)
        now = datetime.now(UTC)
        staff.deleted_at = now
        staff.is_active = False
        self.db.execute(
            delete(StaffAssignment).where(
                StaffAssignment.staff_id == staff.id, StaffAssignment.end_at > now
            )
        )
        self.db.commit()

    # --- Assignments ----------------------------------------------------------

    def _calendar(self, calendar_id: uuid.UUID) -> Calendar:
        calendar = self.db.scalar(
            select(Calendar).where(
                Calendar.id == calendar_id,
                Calendar.operator_id == self.operator_id,
                Calendar.deleted_at.is_(None),
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

    @staticmethod
    def _unavailable_reason(
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
        if not fits_weekly_hours(hours, start_at.astimezone(zone), end_at.astimezone(zone)):
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
            .where(*conditions)
            .order_by(StaffAssignment.start_at, Staff.name)
        )
        return [self._assignment_payload(assignment, name) for assignment, name in rows]

    def candidates(self, calendar_id: uuid.UUID, start_at: datetime) -> list[dict[str, Any]]:
        """Every active staff member, flagged with whether they can take this slot."""
        calendar = self._calendar(calendar_id)
        end_at = start_at + timedelta(minutes=calendar.duration_minutes)
        staff = list(
            self.db.scalars(
                select(Staff)
                .where(
                    Staff.operator_id == self.operator_id,
                    Staff.deleted_at.is_(None),
                    Staff.is_active.is_(True),
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
                member, hours.get(member.id, []), overlaps.get(member.id), start_at, end_at, zone
            )
            result.append(
                {"staff_id": member.id, "name": member.name, "available": reason is None, "reason": reason}
            )
        return result

    def assign(self, data: StaffAssignmentCreate) -> dict[str, Any]:
        calendar = self._calendar(data.calendar_id)
        end_at = data.start_at + timedelta(minutes=calendar.duration_minutes)
        staff = self._staff(data.staff_id, lock=True)
        reason = self._unavailable_reason(
            staff,
            self._hours([staff.id]).get(staff.id, []),
            self._overlaps([staff.id], data.start_at, end_at).get(staff.id),
            data.start_at,
            end_at,
            self._zone(),
        )
        if reason:
            raise ConflictError(reason)
        assignment = StaffAssignment(
            operator_id=self.operator_id,
            staff_id=staff.id,
            calendar_id=calendar.id,
            start_at=data.start_at,
            end_at=end_at,
            role=data.role,
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
        assignment, staff_name = self._assignment(assignment_id)
        assignment.role = data.role
        self.db.commit()
        return self._assignment_payload(assignment, staff_name)

    def unassign(self, assignment_id: uuid.UUID) -> None:
        """Remove staff from a slot and, for an upcoming slot, email them about it."""
        assignment, _ = self._assignment(assignment_id)
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
