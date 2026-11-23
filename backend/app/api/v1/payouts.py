"""Settings → Payments → Payout split.

The connected Stripe account receives a percentage of the ticket price of
each product on an included calendar; the main account keeps the rest plus
all booking fees and taxes. The split is saved on each booking when it is
made, so changing it never alters bookings already taken.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.database import get_db
from app.core.permissions import Permission, require_permission
from app.models.entities import Calendar, CalendarCategory, OperatorSettings
from app.services.order_service import DEFAULT_PAYOUT_SHARE_BPS

router = APIRouter(prefix="/settings/payments/payouts", tags=["Payout split"])
DB = Annotated[Session, Depends(get_db)]


class PayoutCalendar(BaseModel):
    id: uuid.UUID
    name: str
    category: str | None
    is_active: bool
    included: bool


class PayoutSettings(BaseModel):
    payout_share_bps: int = Field(ge=0, le=10_000)
    calendars: list[PayoutCalendar]


class PayoutCalendarUpdate(BaseModel):
    id: uuid.UUID
    included: bool


class PayoutSettingsUpdate(BaseModel):
    payout_share_bps: int = Field(ge=0, le=10_000)
    calendars: list[PayoutCalendarUpdate] = Field(default_factory=list, max_length=1000)


def _read(db: Session, operator_id: uuid.UUID) -> PayoutSettings:
    settings = db.get(OperatorSettings, operator_id)
    rows = db.execute(
        select(Calendar, CalendarCategory.name)
        .outerjoin(CalendarCategory, CalendarCategory.id == Calendar.calendar_category_id)
        .where(Calendar.operator_id == operator_id, Calendar.deleted_at.is_(None))
        .order_by(CalendarCategory.name.nulls_last(), Calendar.name)
    ).all()
    return PayoutSettings(
        payout_share_bps=settings.payout_share_bps if settings else DEFAULT_PAYOUT_SHARE_BPS,
        calendars=[
            PayoutCalendar(
                id=calendar.id,
                name=calendar.name,
                category=category,
                is_active=calendar.is_active,
                included=calendar.payout_included,
            )
            for calendar, category in rows
        ],
    )


@router.get("", response_model=PayoutSettings)
def get_payout_settings(principal: CurrentPrincipal, db: DB):
    require_permission(principal, Permission.MANAGE_PAYMENTS)
    return _read(db, principal.operator_id)


@router.put("", response_model=PayoutSettings)
def update_payout_settings(data: PayoutSettingsUpdate, principal: CurrentPrincipal, db: DB):
    require_permission(principal, Permission.MANAGE_PAYMENTS)
    settings = db.get(OperatorSettings, principal.operator_id)
    if settings is None:
        settings = OperatorSettings(operator_id=principal.operator_id)
        db.add(settings)
    settings.payout_share_bps = data.payout_share_bps
    wanted = {item.id: item.included for item in data.calendars}
    if wanted:
        for calendar in db.scalars(
            select(Calendar).where(
                Calendar.operator_id == principal.operator_id,
                Calendar.id.in_(list(wanted)),
                Calendar.deleted_at.is_(None),
            )
        ):
            calendar.payout_included = wanted[calendar.id]
    db.commit()
    return _read(db, principal.operator_id)
