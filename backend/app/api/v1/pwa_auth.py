from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.app_session import (
    SessionPrincipal,
    bearer_scheme,
    decode_app_session,
    decode_pwa_refresh_session,
    create_pwa_refresh_session,
    validate_session_principal,
)
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.schemas.auth import GHLSessionResponse, PWAHandoffRequest
from app.services.ghl_auth_service import GHLAuthService, required_scopes
from app.services.pwa_auth_service import PWAAuthService

router = APIRouter(prefix="/pwa-auth", tags=["PWA authentication"])
DB = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
STATE_COOKIE_PATH = "/api/v1"
PWA_SESSION_COOKIE = "passport_pwa_session"


def _pwa_cookie_path(settings: Settings) -> str:
    # The installed app can reopen on /app or another SPA route before it
    # calls the refresh endpoint. A root path also avoids browser-specific
    # surprises when Vercel rewrites /api requests to the backend.
    return "/"


def _pwa_session_response(
    access_token: str,
    refresh_token: str,
    access_expires_in: int,
    refresh_expires_in: int,
    settings: Settings,
) -> JSONResponse:
    """Return the normal bearer response and a host-only PWA recovery cookie.

    The browser continues using the bearer token for all Passport API calls. The
    HTTP-only cookie is sent only to the PWA refresh endpoint, so an installed
    iPhone/Android app can recover after its localStorage is unavailable or has
    been evicted without storing a HighLevel credential in the browser.
    """
    response = JSONResponse(
        content=GHLSessionResponse(
            access_token=access_token,
            expires_in=access_expires_in,
        ).model_dump(mode="json")
    )
    response.set_cookie(
        key=PWA_SESSION_COOKIE,
        value=refresh_token,
        max_age=refresh_expires_in,
        httponly=True,
        secure=settings.environment.lower() == "production",
        samesite="lax",
        path=_pwa_cookie_path(settings),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def _pwa_refresh_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    pwa_session: Annotated[str | None, Cookie(alias=PWA_SESSION_COOKIE)] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SessionPrincipal:
    """Prefer the PWA-only recovery cookie; accept a legacy bearer once."""
    if pwa_session:
        return validate_session_principal(decode_pwa_refresh_session(pwa_session, settings), db)
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Passport PWA session required")
    # Existing installations may have a bearer token in browser storage but no
    # recovery cookie. The successful response migrates them automatically.
    return validate_session_principal(decode_app_session(credentials.credentials, settings), db)


def _new_pwa_session_response(
    principal: SessionPrincipal,
    access_token: str,
    expires_in: int,
    settings: Settings,
) -> JSONResponse:
    refresh_token, refresh_expires_in = create_pwa_refresh_session(
        principal,
        settings,
        lifetime_minutes=settings.pwa_session_minutes,
    )
    # The API token remains short lived; the HTTP-only cookie is valid for the
    # configured PWA lifetime. Different audiences prevent either token type
    # from being accepted in the other role.
    return _pwa_session_response(
        access_token,
        refresh_token,
        expires_in,
        refresh_expires_in,
        settings,
    )


PWARefreshPrincipal = Annotated[SessionPrincipal, Depends(_pwa_refresh_principal)]


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
) -> JSONResponse:
    try:
        token, expires_in, principal = PWAAuthService(db, settings).exchange_handoff(request.code)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return _new_pwa_session_response(principal, token, expires_in, settings)


@router.post("/refresh", response_model=GHLSessionResponse)
def pwa_refresh(
    principal: PWARefreshPrincipal,
    db: DB,
    settings: AppSettings,
) -> JSONResponse:
    try:
        token, expires_in, refreshed_principal = PWAAuthService(db, settings).refresh_session(principal)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return _new_pwa_session_response(refreshed_principal, token, expires_in, settings)


@router.post("/logout", status_code=204)
def pwa_logout(
    response: Response,
    db: DB,
    settings: AppSettings,
    pwa_session: Annotated[str | None, Cookie(alias=PWA_SESSION_COOKIE)] = None,
) -> None:
    if pwa_session:
        try:
            principal = decode_pwa_refresh_session(pwa_session, settings)
            PWAAuthService(db, settings).revoke_session(principal)
        except HTTPException:
            # Logout must be safe to repeat even if its old cookie was already rotated or expired.
            pass
    response.delete_cookie(PWA_SESSION_COOKIE, path=_pwa_cookie_path(settings))
