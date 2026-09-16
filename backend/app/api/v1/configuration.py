import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal, SessionPrincipal
from app.core.database import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.configuration import (
    CalendarBlockRead,
    CalendarBlocksReplace,
    CalendarBlockWrite,
    CalendarCreate,
    CalendarDateHourRead,
    CalendarDateHoursReplace,
    CalendarHourRead,
    CalendarHoursReplace,
    CalendarRead,
    CalendarResourceRead,
    CalendarResourcesReplace,
    CalendarUpdate,
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    LocationCreate,
    LocationRead,
    LocationUpdate,
    PushedSlotRead,
    PushedSlotsCreate,
    ResourceCreate,
    ResourceRead,
    ResourceUpdate,
)
from app.services.configuration_service import ConfigurationService


router = APIRouter(tags=["configuration"])
DB = Annotated[Session, Depends(get_db)]


def service(db: Session, principal: SessionPrincipal) -> ConfigurationService:
    return ConfigurationService(db, principal.operator_id)


def require_admin(principal: SessionPrincipal, *, delete: bool = False) -> None:
    require_permission(
        principal,
        Permission.DELETE_CONFIGURATION if delete else Permission.MANAGE_CONFIGURATION,
    )


@router.get("/locations", response_model=list[LocationRead])
def list_locations(principal: CurrentPrincipal, db: DB):
    return service(db, principal).list_locations()


@router.post("/locations", response_model=LocationRead, status_code=status.HTTP_201_CREATED)
def create_location(data: LocationCreate, principal: CurrentPrincipal, db: DB):
    require_admin(principal)
    return service(db, principal).create_location(data)


@router.get("/locations/{entity_id}", response_model=LocationRead)
def get_location(entity_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    return service(db, principal).get_location(entity_id)


@router.patch("/locations/{entity_id}", response_model=LocationRead)
def update_location(data: LocationUpdate, entity_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    require_admin(principal)
    return service(db, principal).update_location(entity_id, data)


@router.delete("/locations/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(entity_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> Response:
    require_admin(principal, delete=True)
    service(db, principal).delete_location(entity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/resources", response_model=list[ResourceRead])
def list_resources(principal: CurrentPrincipal, db: DB):
    return service(db, principal).list_resources()


@router.post("/resources", response_model=ResourceRead, status_code=status.HTTP_201_CREATED)
def create_resource(data: ResourceCreate, principal: CurrentPrincipal, db: DB):
    require_admin(principal)
    return service(db, principal).create_resource(data)


@router.get("/resources/{entity_id}", response_model=ResourceRead)
def get_resource(entity_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    return service(db, principal).get_resource(entity_id)


@router.patch("/resources/{entity_id}", response_model=ResourceRead)
def update_resource(data: ResourceUpdate, entity_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    require_admin(principal)
    return service(db, principal).update_resource(entity_id, data)


@router.delete("/resources/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resource(entity_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> Response:
    require_admin(principal, delete=True)
    service(db, principal).delete_resource(entity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/calendar-categories", response_model=list[CategoryRead])
def list_categories(principal: CurrentPrincipal, db: DB):
    return service(db, principal).list_categories()


@router.post(
    "/calendar-categories", response_model=CategoryRead, status_code=status.HTTP_201_CREATED
)
def create_category(data: CategoryCreate, principal: CurrentPrincipal, db: DB):
    require_admin(principal)
    return service(db, principal).create_category(data)


@router.patch("/calendar-categories/{entity_id}", response_model=CategoryRead)
def update_category(data: CategoryUpdate, entity_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    require_admin(principal)
    return service(db, principal).update_category(entity_id, data)


@router.delete("/calendar-categories/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(entity_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> Response:
    require_admin(principal, delete=True)
    service(db, principal).delete_category(entity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/calendars", response_model=list[CalendarRead])
def list_calendars(
    principal: CurrentPrincipal,
    db: DB,
    category_id: uuid.UUID | None = None,
    departure_location_id: uuid.UUID | None = None,
    is_active: bool | None = None,
):
    return service(db, principal).list_calendars(category_id, departure_location_id, is_active)


@router.post("/calendars", response_model=CalendarRead, status_code=status.HTTP_201_CREATED)
def create_calendar(data: CalendarCreate, principal: CurrentPrincipal, db: DB):
    require_admin(principal)
    return service(db, principal).create_calendar(data)


@router.get("/calendars/{entity_id}", response_model=CalendarRead)
def get_calendar(entity_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    return service(db, principal).get_calendar(entity_id)


@router.patch("/calendars/{entity_id}", response_model=CalendarRead)
def update_calendar(data: CalendarUpdate, entity_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    require_admin(principal)
    return service(db, principal).update_calendar(entity_id, data)


@router.delete("/calendars/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calendar(entity_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> Response:
    require_admin(principal, delete=True)
    service(db, principal).delete_calendar(entity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/calendars/{calendar_id}/hours", response_model=list[CalendarHourRead])
def list_hours(calendar_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    return service(db, principal).list_hours(calendar_id)


@router.put("/calendars/{calendar_id}/hours", response_model=list[CalendarHourRead])
def replace_hours(
    data: CalendarHoursReplace, calendar_id: uuid.UUID, principal: CurrentPrincipal, db: DB
):
    require_admin(principal)
    return service(db, principal).replace_hours(calendar_id, data)


@router.get("/calendars/{calendar_id}/date-hours", response_model=list[CalendarDateHourRead])
def list_date_hours(calendar_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    return service(db, principal).list_date_hours(calendar_id)


@router.put("/calendars/{calendar_id}/date-hours", response_model=list[CalendarDateHourRead])
def replace_date_hours(
    data: CalendarDateHoursReplace, calendar_id: uuid.UUID, principal: CurrentPrincipal, db: DB
):
    require_admin(principal)
    return service(db, principal).replace_date_hours(calendar_id, data)


@router.get("/calendars/{calendar_id}/pushed-slots", response_model=list[PushedSlotRead])
def list_pushed_slots(calendar_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    return service(db, principal).list_pushed_slots(calendar_id)


@router.post(
    "/calendars/{calendar_id}/pushed-slots",
    response_model=list[PushedSlotRead],
    status_code=status.HTTP_201_CREATED,
)
def push_slots(
    data: PushedSlotsCreate, calendar_id: uuid.UUID, principal: CurrentPrincipal, db: DB
):
    require_admin(principal)
    return service(db, principal).push_slots(calendar_id, data)


@router.delete(
    "/calendars/{calendar_id}/pushed-slots/{slot_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_pushed_slot(
    calendar_id: uuid.UUID, slot_id: uuid.UUID, principal: CurrentPrincipal, db: DB
) -> Response:
    require_admin(principal)
    service(db, principal).delete_pushed_slot(calendar_id, slot_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/calendars/{calendar_id}/blocks", response_model=list[CalendarBlockRead])
def replace_blocks(
    data: CalendarBlocksReplace, calendar_id: uuid.UUID, principal: CurrentPrincipal, db: DB
):
    require_admin(principal)
    return service(db, principal).replace_blocks(calendar_id, data)


@router.get("/calendars/{calendar_id}/blocks", response_model=list[CalendarBlockRead])
def list_blocks(calendar_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    return service(db, principal).list_blocks(calendar_id)


@router.post(
    "/calendars/{calendar_id}/blocks",
    response_model=CalendarBlockRead,
    status_code=status.HTTP_201_CREATED,
)
def create_block(
    data: CalendarBlockWrite, calendar_id: uuid.UUID, principal: CurrentPrincipal, db: DB
):
    require_admin(principal)
    return service(db, principal).create_block(calendar_id, data)


@router.patch(
    "/calendars/{calendar_id}/blocks/{block_id}", response_model=CalendarBlockRead
)
def update_block(
    data: CalendarBlockWrite,
    calendar_id: uuid.UUID,
    block_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DB,
):
    require_admin(principal)
    return service(db, principal).update_block(calendar_id, block_id, data)


@router.delete(
    "/calendars/{calendar_id}/blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_block(
    calendar_id: uuid.UUID, block_id: uuid.UUID, principal: CurrentPrincipal, db: DB
) -> Response:
    require_admin(principal, delete=True)
    service(db, principal).delete_block(calendar_id, block_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/calendars/{calendar_id}/resources", response_model=list[CalendarResourceRead])
def list_calendar_resources(calendar_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    return service(db, principal).list_calendar_resources(calendar_id)


@router.put("/calendars/{calendar_id}/resources", response_model=list[CalendarResourceRead])
def replace_calendar_resources(
    data: CalendarResourcesReplace,
    calendar_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DB,
):
    require_admin(principal)
    return service(db, principal).replace_calendar_resources(calendar_id, data)

