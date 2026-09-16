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

logger = logging.getLogger("passport.ghl_oauth")

router = APIRouter(prefix="/integrations/marketplace", tags=["GHL integration"])


@router.get("/oauth/callback")
def oauth_callback(
    code: Annotated[str, Query(min_length=8, max_length=4096)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    state: Annotated[str | None, Query(min_length=20, max_length=512)] = None,
    ghl_oauth_state: Annotated[str | None, Cookie()] = None,
) -> RedirectResponse:
    service = GHLAuthService(db, settings)
    try:
        if state:
            if not ghl_oauth_state or not hmac.compare_digest(state, ghl_oauth_state):
                raise ValueError("OAuth state does not match the installation browser")
            state_row = service.consume_oauth_state(state)
        else:
            state_row = None
        token_payload = service.exchange_code(code)
        if state_row and state_row.expected_location_id and token_payload.get("locationId") != state_row.expected_location_id:
            raise ValueError("OAuth location does not match the installation request")
        location = service.fetch_location(token_payload["locationId"], token_payload["access_token"])
        service.provision_installation(token_payload, location)
    except (httpx.HTTPError, ValueError) as exc:
        # Never expose tokens. The upstream *error* body (no tokens on failure) is
        # logged to diagnose install failures (invalid_grant / redirect mismatch).
        detail = str(exc)
        if isinstance(exc, httpx.HTTPStatusError):
            detail = f"HTTP {exc.response.status_code} from {exc.request.url}: {exc.response.text[:600]}"
        logger.error("GHL installation failed: %s", detail)
        message = quote("HighLevel installation could not be completed")
        return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/integration-result?error={message}")
    return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/integration-result?installed=1")


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
        path="/api/v1/integrations/marketplace",
    )
    return response
