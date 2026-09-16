from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.entities import Calendar, CalendarCategory, DepartureLocation, Operator
from app.schemas.public import (
    PublicCalendar,
    PublicCategoryPage,
    PublicLocation,
    PublicOperatorCatalog,
)

router = APIRouter(prefix="/public", tags=["public catalog"])


def _public_calendar(
    calendar: Calendar,
    category: CalendarCategory | None,
    location: DepartureLocation | None,
) -> PublicCalendar:
    return PublicCalendar(
        id=calendar.id,
        name=calendar.name,
        slug=calendar.slug,
        description=calendar.description,
        duration_minutes=calendar.duration_minutes,
        base_price_minor=calendar.base_price_minor,
        currency=calendar.currency,
        category_id=category.id if category else None,
        category_name=category.name if category else None,
        category_slug=category.slug if category else None,
        category_color=category.display_color if category else None,
        location=PublicLocation(name=location.name, address=location.address) if location else None,
    )


def _active_operator(db: Session, operator_slug: str) -> Operator:
    operator = db.scalar(
        select(Operator).where(
            Operator.slug == operator_slug,
            Operator.is_active.is_(True),
            Operator.public_booking_enabled.is_(True),
        )
    )
    if operator is None:
        raise NotFoundError("Booking page not found")
    return operator


@router.get("/{operator_slug}", response_model=PublicOperatorCatalog)
def public_catalog(
    operator_slug: str, db: Annotated[Session, Depends(get_db)]
) -> PublicOperatorCatalog:
    operator = _active_operator(db, operator_slug)
    rows = db.execute(
        select(Calendar, CalendarCategory, DepartureLocation)
        .outerjoin(CalendarCategory, CalendarCategory.id == Calendar.calendar_category_id)
        .outerjoin(DepartureLocation, DepartureLocation.id == Calendar.departure_location_id)
        .where(
            Calendar.operator_id == operator.id,
            Calendar.is_active.is_(True),
            Calendar.public_booking_enabled.is_(True),
            Calendar.deleted_at.is_(None),
        )
        .order_by(CalendarCategory.sort_order.nulls_last(), Calendar.name)
    )
    return PublicOperatorCatalog(
        name=operator.name,
        slug=operator.slug,
        time_zone=operator.time_zone,
        calendars=[_public_calendar(*row) for row in rows],
    )


@router.get("/{operator_slug}/category/{category_slug}", response_model=PublicCategoryPage)
def public_category(
    operator_slug: str, category_slug: str, db: Annotated[Session, Depends(get_db)]
) -> PublicCategoryPage:
    operator = _active_operator(db, operator_slug)
    category = db.scalar(
        select(CalendarCategory).where(
            CalendarCategory.operator_id == operator.id,
            CalendarCategory.slug == category_slug,
            CalendarCategory.is_active.is_(True),
            CalendarCategory.deleted_at.is_(None),
        )
    )
    if category is None:
        raise NotFoundError("Booking page not found")
    rows = db.execute(
        select(Calendar, DepartureLocation)
        .outerjoin(DepartureLocation, DepartureLocation.id == Calendar.departure_location_id)
        .where(
            Calendar.operator_id == operator.id,
            Calendar.calendar_category_id == category.id,
            Calendar.is_active.is_(True),
            Calendar.public_booking_enabled.is_(True),
            Calendar.deleted_at.is_(None),
        )
        .order_by(Calendar.name)
    ).all()
    # A category page is only public if it actually offers something bookable.
    if not rows:
        raise NotFoundError("Booking page not found")
    return PublicCategoryPage(
        operator_name=operator.name,
        operator_slug=operator.slug,
        time_zone=operator.time_zone,
        category_name=category.name,
        category_slug=category.slug,
        calendars=[_public_calendar(calendar, category, location) for calendar, location in rows],
    )
