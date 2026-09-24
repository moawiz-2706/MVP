import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import Permission, require_permission
from app.models.entities import Booking, MigrationImport, ReconciliationRun
from app.schemas.booking import BookingDetail, BookingUpdate
from app.schemas.fareharbor_replica import (
    BookingCustomFieldsWrite,
    BookingPolicyRead,
    BookingPolicyWrite,
    BookingRescheduleRequest,
    BookingStatusRequest,
    BookingCustomFieldDefinitionRead,
    BookingCustomFieldDefinitionWrite,
    CustomerDetail,
    CustomerListItem,
    CustomerNoteCreate,
    CustomerNoteRead,
    CustomerUpdate,
    MigrationImportCreate,
    MigrationImportRead,
    ReconciliationRunCreate,
    ReconciliationRunRead,
    WeatherClosureRequest,
)
from app.services.booking_admin_service import BookingAdminService
from app.services.fareharbor_replica_service import FareHarborReplicaService

router = APIRouter(tags=["fareharbor-replica"])
DB = Annotated[Session, Depends(get_db)]


def service(db: Session, principal) -> FareHarborReplicaService:
    return FareHarborReplicaService(db, principal.operator_id)


def operate(principal) -> None:
    require_permission(principal, Permission.OPERATE_BOOKINGS)


def manage(principal) -> None:
    require_permission(principal, Permission.MANAGE_CONFIGURATION)


@router.get("/calendars/{calendar_id}/booking-policy", response_model=BookingPolicyRead)
def get_policy(calendar_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    manage(principal)
    return service(db, principal).policy(calendar_id)


@router.put("/calendars/{calendar_id}/booking-policy", response_model=BookingPolicyRead)
def put_policy(calendar_id: uuid.UUID, data: BookingPolicyWrite, principal: CurrentPrincipal, db: DB):
    manage(principal)
    return service(db, principal).replace_policy(calendar_id, data)


@router.get("/booking-custom-fields", response_model=list[BookingCustomFieldDefinitionRead])
def list_custom_fields(principal: CurrentPrincipal, db: DB, calendar_id: uuid.UUID | None = None):
    operate(principal)
    return service(db, principal).list_custom_fields(calendar_id)


@router.post("/booking-custom-fields", response_model=BookingCustomFieldDefinitionRead, status_code=status.HTTP_201_CREATED)
def create_custom_field(data: BookingCustomFieldDefinitionWrite, principal: CurrentPrincipal, db: DB):
    manage(principal)
    return service(db, principal).create_custom_field(data)


@router.delete("/booking-custom-fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_custom_field(field_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    manage(principal)
    service(db, principal).delete_custom_field(field_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/customers", response_model=list[CustomerListItem])
def list_customers(principal: CurrentPrincipal, db: DB, search: str | None = None):
    operate(principal)
    return service(db, principal).customers(search)


@router.get("/customers/{customer_id}", response_model=CustomerDetail)
def get_customer(customer_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    operate(principal)
    return service(db, principal).customer(customer_id)


@router.patch("/customers/{customer_id}", response_model=CustomerListItem)
def patch_customer(customer_id: uuid.UUID, data: CustomerUpdate, principal: CurrentPrincipal, db: DB):
    operate(principal)
    return service(db, principal).update_customer(customer_id, data)


@router.post("/customers/{customer_id}/notes", response_model=CustomerNoteRead, status_code=status.HTTP_201_CREATED)
def create_customer_note(customer_id: uuid.UUID, data: CustomerNoteCreate, principal: CurrentPrincipal, db: DB):
    operate(principal)
    return service(db, principal).add_customer_note(customer_id, data, principal.app_user_id)


@router.post("/bookings/{booking_id}/custom-fields")
def set_booking_custom_fields(booking_id: uuid.UUID, data: BookingCustomFieldsWrite, principal: CurrentPrincipal, db: DB):
    operate(principal)
    return {"values": service(db, principal).set_booking_fields(booking_id, data)}


@router.post("/bookings/{booking_id}/reschedule", response_model=BookingDetail)
def reschedule_booking(booking_id: uuid.UUID, data: BookingRescheduleRequest, principal: CurrentPrincipal, db: DB):
    operate(principal)
    booking = db.scalar(select(Booking).where(Booking.id == booking_id, Booking.operator_id == principal.operator_id))
    if booking is None:
        raise NotFoundError("Booking not found")
    policy = service(db, principal).policy(booking.calendar_id)
    if policy["reschedule_cutoff_minutes"] and data.start_at.astimezone().timestamp() <= booking.start_at.timestamp():
        raise ConflictError("The new start time must be after the current booking time")
    result = BookingAdminService(db, principal.operator_id).update(
        booking_id,
        BookingUpdate(start_at=data.start_at, units=data.units),
    )
    return result


@router.post("/bookings/{booking_id}/status", response_model=BookingDetail)
def set_booking_status(booking_id: uuid.UUID, data: BookingStatusRequest, principal: CurrentPrincipal, db: DB):
    operate(principal)
    return service(db, principal).status(booking_id, data)


@router.post("/bookings/{booking_id}/weather-cancel")
def weather_cancel(data: WeatherClosureRequest, booking_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    operate(principal)
    return service(db, principal).weather_closure(data, principal.app_user_id)


@router.post("/migration/imports", response_model=MigrationImportRead, status_code=status.HTTP_201_CREATED)
def stage_migration(data: MigrationImportCreate, principal: CurrentPrincipal, db: DB):
    manage(principal)
    return service(db, principal).stage_import(data)


@router.get("/migration/imports", response_model=list[MigrationImportRead])
def list_migrations(principal: CurrentPrincipal, db: DB):
    manage(principal)
    return db.scalars(
        select(MigrationImport)
        .where(MigrationImport.operator_id == principal.operator_id)
        .order_by(MigrationImport.created_at.desc())
    ).all()


@router.get("/migration/imports/{import_id}", response_model=MigrationImportRead)
def get_migration(import_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    manage(principal)
    item = db.scalar(select(MigrationImport).where(MigrationImport.id == import_id, MigrationImport.operator_id == principal.operator_id))
    if item is None:
        raise NotFoundError("Migration import not found")
    return item


@router.post("/migration/imports/{import_id}/commit", response_model=MigrationImportRead)
def commit_migration(import_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    manage(principal)
    return service(db, principal).commit_import(import_id)


@router.post("/reconciliation/runs", response_model=ReconciliationRunRead, status_code=status.HTTP_201_CREATED)
def create_reconciliation(data: ReconciliationRunCreate, principal: CurrentPrincipal, db: DB):
    manage(principal)
    return service(db, principal).reconciliation(data)


@router.get("/reconciliation/runs", response_model=list[ReconciliationRunRead])
def list_reconciliations(principal: CurrentPrincipal, db: DB):
    manage(principal)
    return db.scalars(
        select(ReconciliationRun)
        .where(ReconciliationRun.operator_id == principal.operator_id)
        .order_by(ReconciliationRun.created_at.desc())
    ).all()


@router.get("/reconciliation/runs/{run_id}", response_model=ReconciliationRunRead)
def get_reconciliation(run_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    manage(principal)
    run = db.scalar(select(ReconciliationRun).where(ReconciliationRun.id == run_id, ReconciliationRun.operator_id == principal.operator_id))
    if run is None:
        raise NotFoundError("Reconciliation run not found")
    return run
