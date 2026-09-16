from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.database import get_db
from app.schemas.availability import (
    AvailabilityCheckRequest,
    AvailabilityCheckResponse,
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
def public_availability(operator_slug: str, calendar_slug: str, date: date, db: DB):
    return AvailabilityService(db).public_day(operator_slug, calendar_slug, date)

