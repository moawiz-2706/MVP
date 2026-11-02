from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.database import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.pwa import (
    PWACheckInRequest,
    PWAClosurePreview,
    PWACloseDepartureRequest,
    PWACloseDepartureResponse,
    PWAManifestParticipant,
    PWAManifestResponse,
    PWABootstrapResponse,
    PWADashboardResponse,
    PWADeparturesResponse,
    PWAUniversalSearchResponse,
)
from app.services.departure_board_service import DepartureBoardService
from app.services.manifest_service import ManifestService
from app.services.weather_closure import close_departure, closure_preview
from app.services.pwa_workspace_service import PWAWorkspaceService, parse_search_types


router = APIRouter(prefix="/pwa", tags=["PWA workspace"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/bootstrap", response_model=PWABootstrapResponse)
def bootstrap(principal: CurrentPrincipal, db: DB) -> PWABootstrapResponse:
    """Load shell identity, permissions, feature availability, and badge counts once."""

    require_permission(principal, Permission.VIEW_BOOKINGS)
    return PWAWorkspaceService(db, principal).bootstrap()


@router.get("/dashboard", response_model=PWADashboardResponse)
def dashboard(
    principal: CurrentPrincipal,
    db: DB,
    target_date: Annotated[date | None, Query(alias="date")] = None,
) -> PWADashboardResponse:
    require_permission(principal, Permission.VIEW_BOOKINGS)
    return PWAWorkspaceService(db, principal).dashboard(target_date)


@router.get("/departures", response_model=PWADeparturesResponse)
def departures(
    principal: CurrentPrincipal,
    db: DB,
    target_date: Annotated[date, Query(alias="date")],
    calendar_id: uuid.UUID | None = None,
) -> PWADeparturesResponse:
    """Every departure offered on an operator-local day, including empty ones."""

    require_permission(principal, Permission.VIEW_BOOKINGS)
    return DepartureBoardService(db, principal.operator_id).day(target_date, calendar_id=calendar_id)


@router.get("/manifest", response_model=PWAManifestResponse)
def manifest(
    principal: CurrentPrincipal,
    db: DB,
    calendar_id: uuid.UUID,
    start_at: datetime,
) -> PWAManifestResponse:
    """Passenger manifest for one exact departure."""

    require_permission(principal, Permission.VIEW_BOOKINGS)
    return ManifestService(db, principal.operator_id).manifest(calendar_id, start_at)


@router.post("/participants/{participant_id}/check-in", response_model=PWAManifestParticipant)
def check_in(
    participant_id: uuid.UUID,
    data: PWACheckInRequest,
    principal: CurrentPrincipal,
    db: DB,
) -> PWAManifestParticipant:
    require_permission(principal, Permission.OPERATE_BOOKINGS)
    return ManifestService(db, principal.operator_id).set_check_in(
        participant_id, data.checked_in, principal.app_user_id
    )


@router.get("/departures/closure-preview", response_model=PWAClosurePreview)
def departure_closure_preview(
    principal: CurrentPrincipal,
    db: DB,
    calendar_id: uuid.UUID,
    start_at: datetime,
) -> PWAClosurePreview:
    """Everything a weather closure of this departure would affect. Admin only."""

    require_permission(principal, Permission.MANAGE_CONFIGURATION)
    return closure_preview(db, principal.operator_id, calendar_id, start_at)


@router.post("/departures/close", response_model=PWACloseDepartureResponse)
def close_departure_for_weather(
    data: PWACloseDepartureRequest,
    principal: CurrentPrincipal,
    db: DB,
) -> PWACloseDepartureResponse:
    """Close one departure: block sales, cancel and refund its bookings. Admin only."""

    require_permission(principal, Permission.MANAGE_CONFIGURATION)
    return close_departure(db, principal.operator_id, principal.app_user_id, data)


@router.get("/search", response_model=PWAUniversalSearchResponse)
def universal_search(
    q: Annotated[str, Query(min_length=2, max_length=100)],
    principal: CurrentPrincipal,
    db: DB,
    types: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=30)] = 12,
) -> PWAUniversalSearchResponse:
    require_permission(principal, Permission.VIEW_BOOKINGS)
    try:
        selected_types = parse_search_types(types)
        return PWAWorkspaceService(db, principal).search(q, types=selected_types, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
