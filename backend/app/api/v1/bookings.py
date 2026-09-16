import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.permissions import Permission, is_admin, require_permission
from app.models.entities import Operator
from app.schemas.booking import (
    BookingDetail,
    BookingListItem,
    BookingNoteCreate,
    BookingNoteRead,
    BookingUpdate,
    DashboardSlot,
)
from app.schemas.order import OrderCreateRequest, OrderCreateResponse
from app.services.booking_admin_service import BookingAdminService
from app.services.order_service import OrderService
from app.services.outbox_service import OutboxService

logger = logging.getLogger("passport.bookings")

router = APIRouter(tags=["bookings"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/bookings", response_model=list[BookingListItem])
def list_bookings(
    range_start: datetime,
    range_end: datetime,
    principal: CurrentPrincipal,
    db: DB,
    calendar_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    status: str | None = None,
    search: str | None = None,
):
    require_permission(principal, Permission.VIEW_BOOKINGS)
    return BookingAdminService(db, principal.operator_id).list(
        range_start,
        range_end,
        calendar_id=calendar_id,
        category_id=category_id,
        booking_status=status,
        search=search,
    )


@router.get("/booking-slots", response_model=list[DashboardSlot])
def booking_slots(
    range_start: datetime,
    range_end: datetime,
    principal: CurrentPrincipal,
    db: DB,
    calendar_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    search: str | None = None,
):
    require_permission(principal, Permission.VIEW_BOOKINGS)
    return BookingAdminService(db, principal.operator_id).slots(
        range_start, range_end, calendar_id=calendar_id, category_id=category_id, search=search
    )


@router.get("/bookings/{booking_id}", response_model=BookingDetail)
def booking_detail(booking_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    require_permission(principal, Permission.VIEW_BOOKINGS)
    return BookingAdminService(db, principal.operator_id).detail(booking_id)


@router.post("/bookings", response_model=OrderCreateResponse, status_code=status.HTTP_201_CREATED)
def create_booking(
    data: OrderCreateRequest,
    principal: CurrentPrincipal,
    db: DB,
    settings: Annotated[Settings, Depends(get_settings)],
):
    require_permission(principal, Permission.OPERATE_BOOKINGS)
    operator_slug = db.scalar(select(Operator.slug).where(Operator.id == principal.operator_id))
    return OrderService(db, settings).create(operator_slug, data)


@router.patch("/bookings/{booking_id}", response_model=BookingDetail)
def update_booking(
    data: BookingUpdate, booking_id: uuid.UUID, principal: CurrentPrincipal, db: DB
):
    require_permission(principal, Permission.OPERATE_BOOKINGS)
    return BookingAdminService(db, principal.operator_id).update(booking_id, data)


@router.post("/bookings/{booking_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
def cancel_booking(booking_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> Response:
    require_permission(principal, Permission.OPERATE_BOOKINGS)
    BookingAdminService(db, principal.operator_id).cancel(booking_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/bookings/{booking_id}/notes",
    response_model=BookingNoteRead,
    status_code=status.HTTP_201_CREATED,
)
def add_note(data: BookingNoteCreate, booking_id: uuid.UUID, principal: CurrentPrincipal, db: DB):
    require_permission(principal, Permission.OPERATE_BOOKINGS)
    return BookingAdminService(db, principal.operator_id).add_note(
        booking_id, data.body, principal.app_user_id
    )


@router.delete("/bookings/{booking_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    booking_id: uuid.UUID, note_id: uuid.UUID, principal: CurrentPrincipal, db: DB
) -> Response:
    require_permission(principal, Permission.OPERATE_BOOKINGS)
    BookingAdminService(db, principal.operator_id).delete_note(
        booking_id, note_id, user_id=principal.app_user_id, is_admin=is_admin(principal)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/orders/{order_id}/retry-ghl-sync", status_code=status.HTTP_204_NO_CONTENT)
def retry_ghl(
    order_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DB,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    require_permission(principal, Permission.OPERATE_BOOKINGS)
    BookingAdminService(db, principal.operator_id).retry_ghl(order_id)
    # Resetting the jobs to pending is not a retry on its own: without a scheduler
    # nothing would pick them up. Run them now so the button does what it says.
    # Failures are left queued with backoff rather than surfaced as a 500.
    try:
        OutboxService(db, settings).process(limit=5)
    except Exception:
        logger.exception("Inline outbox processing failed during manual GHL retry")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

