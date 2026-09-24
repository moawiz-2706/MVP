from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.entities import (
    Calendar,
    CalendarCategory,
    CalendarRate,
    CalendarRateResource,
    CustomerType,
    DepartureLocation,
    Operator,
    Resource,
)
from app.schemas.public import (
    PublicCalendar,
    PublicCategoryPage,
    PublicLocation,
    PublicOperatorCatalog,
    PublicRate,
    PublicRateResource,
)

router = APIRouter(prefix="/public", tags=["public catalog"])


def _operator_time_zone(operator: Operator) -> str:
    return (operator.time_zone or "UTC").strip() or "UTC"


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
    operator_slug: str, db: Annotated[Session, Depends(get_db)], response: Response
) -> PublicOperatorCatalog:
    response.headers["Cache-Control"] = (
        "public, s-maxage=30, max-age=30, stale-while-revalidate=120"
    )
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
        time_zone=_operator_time_zone(operator),
        calendars=[_public_calendar(*row) for row in rows],
    )


@router.get("/{operator_slug}/category/{category_slug}", response_model=PublicCategoryPage)
def public_category(
    operator_slug: str,
    category_slug: str,
    db: Annotated[Session, Depends(get_db)],
    response: Response,
) -> PublicCategoryPage:
    response.headers["Cache-Control"] = (
        "public, s-maxage=30, max-age=30, stale-while-revalidate=120"
    )
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
        time_zone=_operator_time_zone(operator),
        category_name=category.name,
        category_slug=category.slug,
        calendars=[_public_calendar(calendar, category, location) for calendar, location in rows],
    )


@router.get("/{operator_slug}/calendars/{calendar_slug}/rates", response_model=list[PublicRate])
def public_rates(
    operator_slug: str,
    calendar_slug: str,
    db: Annotated[Session, Depends(get_db)],
    response: Response,
) -> list[PublicRate]:
    response.headers["Cache-Control"] = "public, s-maxage=30, max-age=30, stale-while-revalidate=120"
    row = db.execute(
        select(Calendar, Operator)
        .join(Operator, Operator.id == Calendar.operator_id)
        .where(
            Operator.slug == operator_slug,
            Operator.is_active.is_(True),
            Operator.public_booking_enabled.is_(True),
            Calendar.slug == calendar_slug,
            Calendar.is_active.is_(True),
            Calendar.public_booking_enabled.is_(True),
            Calendar.deleted_at.is_(None),
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Booking page not found")
    calendar, _operator = row
    rates = db.execute(
        select(CalendarRate, CustomerType)
        .join(CustomerType, CustomerType.id == CalendarRate.customer_type_id)
        .where(
            CalendarRate.calendar_id == calendar.id,
            CalendarRate.deleted_at.is_(None),
            CalendarRate.is_active.is_(True),
            CustomerType.deleted_at.is_(None),
            CustomerType.is_active.is_(True),
        )
        .order_by(CalendarRate.name_snapshot)
    ).all()
    result: list[PublicRate] = []
    for rate, customer_type in rates:
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
