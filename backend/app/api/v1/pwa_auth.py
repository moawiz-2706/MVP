from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.schemas.auth import GHLSessionResponse, PWAHandoffRequest
from app.services.ghl_auth_service import GHLAuthService, required_scopes
from app.services.pwa_auth_service import PWAAuthService

router = APIRouter(prefix="/pwa-auth", tags=["PWA authentication"])
DB = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
STATE_COOKIE_PATH = "/api/v1"


@router.get("/highlevel/start")
def pwa_highlevel_start(
    db: DB,
    settings: AppSettings,
    location_id: Annotated[str | None, Query(max_length=100)] = None,
) -> RedirectResponse:
    state = GHLAuthService(db, settings).create_oauth_state(
        expected_location_id=location_id,
        flow="pwa_login",
    )
    params = {
        "client_id": settings.ghl_client_id,
        "redirect_uri": settings.ghl_oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(sorted(required_scopes(settings))),
        "state": state,
    }
    response = RedirectResponse(f"{settings.ghl_oauth_authorize_url}?{urlencode(params)}")
    response.set_cookie(
        "pwa_oauth_state",
        state,
        max_age=600,
        httponly=True,
        secure=settings.environment.lower() == "production",
        samesite="lax",
        path=STATE_COOKIE_PATH,
    )
    return response


@router.post("/exchange", response_model=GHLSessionResponse)
def exchange_pwa_handoff(
    request: PWAHandoffRequest,
    db: DB,
    settings: AppSettings,
) -> GHLSessionResponse:
    try:
        token, expires_in = PWAAuthService(db, settings).exchange_handoff(request.code)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return GHLSessionResponse(access_token=token, expires_in=expires_in)


@router.post("/refresh", response_model=GHLSessionResponse)
def pwa_refresh(
    principal: CurrentPrincipal,
    db: DB,
    settings: AppSettings,
) -> GHLSessionResponse:
    try:
        token, expires_in = PWAAuthService(db, settings).refresh_session(principal)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return GHLSessionResponse(access_token=token, expires_in=expires_in)


@router.post("/logout", status_code=204)
def pwa_logout() -> None:
    return None
