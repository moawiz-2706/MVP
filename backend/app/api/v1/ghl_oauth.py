import hmac
import logging
from typing import Annotated
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.services.ghl_auth_service import REQUIRED_SCOPES, GHLAuthService
from app.services.pwa_auth_service import PWAAuthService

logger = logging.getLogger("passport.ghl_oauth")

router = APIRouter(prefix="/integrations/marketplace", tags=["GHL integration"])

OAUTH_STATE_COOKIE_PATH = "/api/v1/integrations/marketplace"


def _integration_redirect(settings: Settings, suffix: str) -> RedirectResponse:
    response = RedirectResponse(f"{settings.frontend_url.rstrip('/')}{suffix}")
    response.delete_cookie("ghl_oauth_state", path=OAUTH_STATE_COOKIE_PATH)
    response.delete_cookie("pwa_oauth_state", path="/api/v1")
    return response


@router.get("/oauth/callback")
def oauth_callback(
    code: Annotated[str, Query(min_length=8, max_length=4096)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    state: Annotated[str, Query(min_length=20, max_length=512)],
    ghl_oauth_state: Annotated[str | None, Cookie()] = None,
    pwa_oauth_state: Annotated[str | None, Cookie()] = None,
) -> RedirectResponse:
    service = GHLAuthService(db, settings)
    pwa_flow = bool(
        pwa_oauth_state and hmac.compare_digest(state, pwa_oauth_state)
    )
    try:
        if not pwa_flow and (
            not ghl_oauth_state or not hmac.compare_digest(state, ghl_oauth_state)
        ):
            raise ValueError("OAuth state does not match the installation browser")
        state_row = service.consume_oauth_state(state)
        if pwa_flow != (state_row.flow == "pwa_login"):
            raise ValueError("OAuth flow does not match the login browser")
        token_payload = service.exchange_code(code)
        if state_row and state_row.expected_location_id and token_payload.get("locationId") != state_row.expected_location_id:
            raise ValueError("OAuth location does not match the installation request")
        if state_row.flow == "pwa_login":
            principal = PWAAuthService(db, settings).login_with_highlevel(
                token_payload,
                expected_location_id=state_row.expected_location_id,
            )
            handoff = PWAAuthService(db, settings).create_handoff(principal)
            return _integration_redirect(settings, f"/app#pwa_code={quote(handoff)}")
        location = service.fetch_location(token_payload["locationId"], token_payload["access_token"])
        service.provision_installation(token_payload, location)
    except (httpx.HTTPError, ValueError) as exc:
        # Never expose tokens. The upstream *error* body (no tokens on failure) is
        # logged to diagnose install failures (invalid_grant / redirect mismatch).
        detail = str(exc)
        if isinstance(exc, httpx.HTTPStatusError):
            detail = f"HTTP {exc.response.status_code} from {exc.request.url}: {exc.response.text[:600]}"
        logger.error("GHL installation failed: %s", detail)
        message = quote("HighLevel login could not be completed" if pwa_flow else "HighLevel installation could not be completed")
        return _integration_redirect(settings, f"/app?pwa_auth_error={message}" if pwa_flow else f"/integration-result?error={message}")
    except Exception:
        logger.exception("Unexpected HighLevel OAuth callback failure")
        message = quote("HighLevel login could not be completed" if pwa_flow else "HighLevel installation could not be completed")
        return _integration_redirect(settings, f"/app?pwa_auth_error={message}" if pwa_flow else f"/integration-result?error={message}")
    return _integration_redirect(settings, "/integration-result?installed=1")


@router.get("/oauth/start")
def oauth_start(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    location_id: Annotated[str | None, Query(max_length=100)] = None,
) -> RedirectResponse:
    state = GHLAuthService(db, settings).create_oauth_state(expected_location_id=location_id)
    params = {
        "client_id": settings.ghl_client_id,
        "redirect_uri": settings.ghl_oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(sorted(REQUIRED_SCOPES)),
        "state": state,
    }
    response = RedirectResponse(f"{settings.ghl_oauth_authorize_url}?{urlencode(params)}")
    response.set_cookie(
        "ghl_oauth_state",
        state,
        max_age=600,
        httponly=True,
        secure=settings.environment.lower() == "production",
        samesite="lax",
        path=OAUTH_STATE_COOKIE_PATH,
    )
    return response
