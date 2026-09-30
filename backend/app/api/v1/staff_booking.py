from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.entities import (
    BookingCustomFieldDefinition,
    Calendar,
    CalendarRate,
    CalendarRateResource,
    CustomerType,
    Operator,
    PublicAccessCredential,
    Resource,
    Staff,
)
from app.schemas.availability import PublicAvailabilityResponse
from app.schemas.order import OrderCreateRequest, OrderCreateResponse
from app.schemas.public import PublicCustomField, PublicRate, PublicRateResource
from app.schemas.staff_booking import StaffBookingContext
from app.services.availability_service import AvailabilityService
from app.services.order_service import OrderService
from app.services.public_access_service import PublicAccessService
from app.core.config import Settings, get_settings

router = APIRouter(prefix="/staff-booking", tags=["staff-booking"])
DB = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def _staff_for_token(db: Session, token: str, *, touch: bool = False) -> Staff:
    credential = PublicAccessService(db).verify(
        token, purpose="staff_booking", touch=touch
    )
    if credential.staff_id is None:
        raise NotFoundError("Staff booking link not found")
    staff = db.scalar(
        select(Staff).where(
            Staff.id == credential.staff_id,
            Staff.operator_id == credential.operator_id,
            Staff.is_active.is_(True),
            Staff.deleted_at.is_(None),
        )
    )
    if staff is None:
        raise NotFoundError("Staff booking link is inactive")
    return staff


def _calendar_for_staff(db: Session, staff: Staff, calendar_id: uuid.UUID) -> Calendar:
    calendar = db.scalar(
        select(Calendar).where(
            Calendar.id == calendar_id,
            Calendar.operator_id == staff.operator_id,
            Calendar.is_active.is_(True),
            Calendar.deleted_at.is_(None),
        )
    )
    if calendar is None:
        raise NotFoundError("Calendar not found")
    return calendar


@router.get("/{token}/context", response_model=StaffBookingContext)
def staff_booking_context(token: str, db: DB):
    staff = _staff_for_token(db, token)
    operator = db.scalar(select(Operator).where(Operator.id == staff.operator_id))
    if operator is None or not operator.is_active:
        raise NotFoundError("Staff booking link is inactive")
    calendars = list(
        db.scalars(
            select(Calendar)
            .where(
                Calendar.operator_id == operator.id,
                Calendar.is_active.is_(True),
                Calendar.deleted_at.is_(None),
            )
            .order_by(Calendar.name)
        )
    )
    return StaffBookingContext(
        staff_id=staff.id,
        staff_name=staff.name,
        operator_name=operator.name,
        time_zone=operator.time_zone or "UTC",
        calendars=calendars,
    )


@router.get(
    "/{token}/calendars/{calendar_id}/availability",
    response_model=PublicAvailabilityResponse,
)
def staff_booking_availability(token: str, calendar_id: uuid.UUID, date: date, db: DB):
    staff = _staff_for_token(db, token)
    _calendar_for_staff(db, staff, calendar_id)
    return AvailabilityService(db).calendar_day(calendar_id, staff.operator_id, date)


@router.get("/{token}/calendars/{calendar_id}/rates", response_model=list[PublicRate])
def staff_booking_rates(token: str, calendar_id: uuid.UUID, db: DB):
    staff = _staff_for_token(db, token)
    calendar = _calendar_for_staff(db, staff, calendar_id)
    rows = db.execute(
        select(CalendarRate, CustomerType)
        .join(CustomerType, CustomerType.id == CalendarRate.customer_type_id)
        .where(
            CalendarRate.calendar_id == calendar.id,
            CalendarRate.operator_id == staff.operator_id,
            CalendarRate.deleted_at.is_(None),
            CalendarRate.is_active.is_(True),
            CustomerType.deleted_at.is_(None),
            CustomerType.is_active.is_(True),
        )
        .order_by(CalendarRate.name_snapshot)
    ).all()
    result: list[PublicRate] = []
    for rate, customer_type in rows:
        resources = db.execute(
            select(
                CalendarRateResource.resource_id,
                Resource.name,
                CalendarRateResource.quantity_per_unit,
                Resource.quantity,
            )
            .join(Resource, Resource.id == CalendarRateResource.resource_id)
            .where(CalendarRateResource.rate_id == rate.id)
            .order_by(Resource.name)
        ).all()
        result.append(
            PublicRate(
                id=rate.id,
                customer_type_name=customer_type.name,
                customer_type_plural_name=customer_type.plural_name,
                note=customer_type.note or rate.note_snapshot,
                seat_count=customer_type.seat_count,
                price_minor=rate.price_minor,
                booking_fee_bps=rate.booking_fee_bps,
                tax_bps=rate.tax_bps,
                resources=[
                    PublicRateResource(
                        resource_id=resource_id,
                        name=name,
                        quantity_per_unit=quantity_per_unit,
                        total_quantity=quantity,
                    )
                    for resource_id, name, quantity_per_unit, quantity in resources
                ],
            )
        )
    return result


@router.get(
    "/{token}/calendars/{calendar_id}/custom-fields",
    response_model=list[PublicCustomField],
)
def staff_booking_custom_fields(token: str, calendar_id: uuid.UUID, db: DB):
    staff = _staff_for_token(db, token)
    calendar = _calendar_for_staff(db, staff, calendar_id)
    return [
        PublicCustomField(
            id=field.id,
            key=field.key,
            label=field.label,
            field_type=field.field_type,
            required=field.required,
            options=field.options,
        )
        for field in db.scalars(
            select(BookingCustomFieldDefinition)
            .where(
                BookingCustomFieldDefinition.operator_id == staff.operator_id,
                BookingCustomFieldDefinition.active.is_(True),
                (BookingCustomFieldDefinition.calendar_id == calendar.id)
                | (BookingCustomFieldDefinition.calendar_id.is_(None)),
            )
            .order_by(BookingCustomFieldDefinition.created_at)
        )
    ]


@router.post("/{token}/orders", response_model=OrderCreateResponse, status_code=201)
def create_staff_booking(
    token: str,
    data: OrderCreateRequest,
    db: DB,
    settings: AppSettings,
    checkout_key: str | None = Header(default=None, alias="X-Staff-Booking-Key"),
):
    staff = _staff_for_token(db, token, touch=True)
    operator = db.scalar(select(Operator).where(Operator.id == staff.operator_id))
    if operator is None or not operator.is_active:
        raise NotFoundError("Staff booking link is inactive")
    return OrderService(db, settings).create(
        operator.slug,
        data,
        checkout_key=checkout_key or f"staff:{staff.id}:{uuid.uuid4()}",
        allow_payment_override=True,
        allow_private_operator=True,
    )
