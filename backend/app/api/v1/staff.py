import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal, SessionPrincipal
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.permissions import Permission, require_permission
from app.models.entities import Calendar, Staff, StaffAssignment
from app.schemas.staff import (
    StaffAssignmentCreate,
    StaffAssignmentRead,
    StaffAssignmentUpdate,
    StaffCandidate,
    StaffCreate,
    StaffRead,
    StaffRoleUpdate,
    StaffUpdate,
)
from app.services.outbox_service import OutboxService
from app.services.staff_service import StaffService

logger = logging.getLogger("passport.staff")

router = APIRouter(tags=["staff"])
DB = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def service(db: Session, principal: SessionPrincipal) -> StaffService:
    return StaffService(db, principal.operator_id)


def _send_now(db: Session, settings: Settings) -> None:
    # Contact syncs and "you've been assigned" emails go out immediately rather
    # than waiting for the daily cron. The change is already committed; anything
    # that fails here stays queued with backoff and the cron retries it.
    try:
        OutboxService(db, settings).process(limit=5)
    except Exception:
        logger.exception("Inline outbox processing failed; jobs remain queued for retry")


# Managing the staff roster is configuration (admins); putting staff on a
# slot is day-to-day booking operation, open to every operator user.


@router.get("/staff", response_model=list[StaffRead])
def list_staff(principal: CurrentPrincipal, db: DB):
    return service(db, principal).list_staff()


@router.post("/staff", response_model=StaffRead, status_code=status.HTTP_201_CREATED)
def create_staff(data: StaffCreate, principal: CurrentPrincipal, db: DB, settings: AppSettings):
    require_permission(principal, Permission.MANAGE_CONFIGURATION)
    staff_service = service(db, principal)
    result = staff_service.create_staff(data)
    _send_now(db, settings)
    # Inline outbox processing may have persisted the GHL user ID or a clear
    # failure/manual-review status; return the refreshed record to the UI.
    return staff_service.get_staff(result["id"])


@router.get("/staff/{staff_id}", response_model=StaffRead)
def get_staff(staff_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    return service(db, principal).get_staff(staff_id)


@router.patch("/staff/{staff_id}", response_model=StaffRead)
def update_staff(
    data: StaffUpdate, staff_id: uuid.UUID, principal: CurrentPrincipal, db: DB, settings: AppSettings
):
    require_permission(principal, Permission.MANAGE_CONFIGURATION)
    staff_service = service(db, principal)
    result = staff_service.update_staff(staff_id, data)
    _send_now(db, settings)
    return staff_service.get_staff(result["id"])


@router.patch("/staff/{staff_id}/custom-role", response_model=StaffRead)
def update_custom_role(
    data: StaffRoleUpdate, staff_id: uuid.UUID, principal: CurrentPrincipal, db: DB
):
    require_permission(principal, Permission.MANAGE_CONFIGURATION)
    return service(db, principal).update_custom_role(staff_id, data)


@router.delete("/staff/{staff_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_staff(staff_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> Response:
    require_permission(principal, Permission.DELETE_CONFIGURATION)
    service(db, principal).delete_staff(staff_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/staff-assignments", response_model=list[StaffAssignmentRead])
def list_assignments(
    range_start: datetime,
    range_end: datetime,
    principal: CurrentPrincipal,
    db: DB,
    calendar_id: uuid.UUID | None = None,
    staff_id: uuid.UUID | None = None,
):
    require_permission(principal, Permission.VIEW_BOOKINGS)
    return service(db, principal).list_assignments(
        range_start, range_end, calendar_id=calendar_id, staff_id=staff_id
    )


@router.get("/staff-assignments/conflicts")
def assignment_conflicts(
    principal: CurrentPrincipal,
    db: DB,
    range_start: datetime | None = None,
    range_end: datetime | None = None,
):
    require_permission(principal, Permission.VIEW_BOOKINGS)
    start = range_start or datetime.now(UTC)
    end = range_end or (start + timedelta(days=30))
    rows = list(
        db.execute(
            select(StaffAssignment, Staff, Calendar)
            .join(Staff, Staff.id == StaffAssignment.staff_id)
            .join(Calendar, Calendar.id == StaffAssignment.calendar_id)
            .where(
                StaffAssignment.operator_id == principal.operator_id,
                StaffAssignment.start_at < end,
                StaffAssignment.end_at > start,
            )
            .order_by(StaffAssignment.staff_id, StaffAssignment.start_at)
        )
    )
    conflicts = []
    previous_by_staff: dict[uuid.UUID, tuple[StaffAssignment, Staff, Calendar]] = {}
    for assignment, staff, calendar in rows:
        previous = previous_by_staff.get(assignment.staff_id)
        if previous and previous[0].end_at > assignment.start_at:
            conflicts.append(
                {
                    "staff_id": staff.id,
                    "staff_name": staff.name,
                    "first_assignment_id": previous[0].id,
                    "first_calendar_id": previous[2].id,
                    "first_calendar_name": previous[2].name,
                    "first_start_at": previous[0].start_at,
                    "first_end_at": previous[0].end_at,
                    "second_assignment_id": assignment.id,
                    "second_calendar_id": calendar.id,
                    "second_calendar_name": calendar.name,
                    "second_start_at": assignment.start_at,
                    "second_end_at": assignment.end_at,
                    "severity": "error",
                }
            )
        if previous is None or assignment.end_at > previous[0].end_at:
            previous_by_staff[assignment.staff_id] = (assignment, staff, calendar)
    return {"range_start": start, "range_end": end, "conflicts": conflicts, "count": len(conflicts)}


@router.get("/staff-assignments/candidates", response_model=list[StaffCandidate])
def assignment_candidates(
    calendar_id: uuid.UUID,
    start_at: datetime,
    principal: CurrentPrincipal,
    db: DB,
    required_role: str | None = None,
):
    require_permission(principal, Permission.VIEW_BOOKINGS)
    return service(db, principal).candidates(calendar_id, start_at, required_role=required_role)


@router.post(
    "/staff-assignments", response_model=StaffAssignmentRead, status_code=status.HTTP_201_CREATED
)
def assign_staff(
    data: StaffAssignmentCreate, principal: CurrentPrincipal, db: DB, settings: AppSettings
):
    require_permission(principal, Permission.OPERATE_BOOKINGS)
    result = service(db, principal).assign(data)
    _send_now(db, settings)
    return result


@router.patch("/staff-assignments/{assignment_id}", response_model=StaffAssignmentRead)
def update_assignment(
    data: StaffAssignmentUpdate, assignment_id: uuid.UUID, principal: CurrentPrincipal, db: DB
):
    require_permission(principal, Permission.OPERATE_BOOKINGS)
    return service(db, principal).update_assignment(assignment_id, data)


@router.delete("/staff-assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def unassign_staff(
    assignment_id: uuid.UUID, principal: CurrentPrincipal, db: DB, settings: AppSettings
) -> Response:
    require_permission(principal, Permission.OPERATE_BOOKINGS)
    service(db, principal).unassign(assignment_id)
    _send_now(db, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
