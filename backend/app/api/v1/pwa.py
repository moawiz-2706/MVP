from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.database import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.pwa import (
    PWABootstrapResponse,
    PWADashboardResponse,
    PWAUniversalSearchResponse,
)
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
