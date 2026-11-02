import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.database import get_db
from app.schemas.availability import (
    AvailabilityCheckRequest,
    AvailabilityCheckResponse,
    AvailabilityMonthResponse,
    PublicAvailabilityResponse,
)
from app.services.availability_service import AvailabilityService

router = APIRouter(tags=["availability"])
DB = Annotated[Session, Depends(get_db)]


@router.post("/availability/check", response_model=AvailabilityCheckResponse)
def check_availability(data: AvailabilityCheckRequest, principal: CurrentPrincipal, db: DB):
    return AvailabilityService(db).check(
        data.calendar_id, data.start_at, data.units, operator_id=principal.operator_id
    )


@router.get(
    "/public/{operator_slug}/calendars/{calendar_slug}/availability",
    response_model=PublicAvailabilityResponse,
)
def public_availability(
    operator_slug: str,
    calendar_slug: str,
    date: date,
    db: DB,
    response: Response,
    timezone: str | None = None,
):
    response.headers["Cache-Control"] = "public, s-maxage=3, max-age=3, stale-while-revalidate=7"
    return AvailabilityService(db).public_day(
        operator_slug, calendar_slug, date, display_timezone=timezone
    )


@router.get(
    "/public/{operator_slug}/calendars/{calendar_slug}/availability/month",
    response_model=AvailabilityMonthResponse,
)
def public_availability_month(
    operator_slug: str,
    calendar_slug: str,
    month: Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
    db: DB,
    response: Response,
):
    """Bookable days for the booking page's month calendar."""
    response.headers["Cache-Control"] = "public, s-maxage=30, max-age=30, stale-while-revalidate=60"
    year, month_number = (int(part) for part in month.split("-"))
    return AvailabilityService(db).public_month(operator_slug, calendar_slug, year, month_number)


@router.get(
    "/calendars/{calendar_id}/availability",
    response_model=PublicAvailabilityResponse,
)
def calendar_availability(
    calendar_id: uuid.UUID,
    date: date,
    principal: CurrentPrincipal,
    db: DB,
):
    return AvailabilityService(db).calendar_day(calendar_id, principal.operator_id, date)
