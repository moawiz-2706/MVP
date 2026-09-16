import logging
from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.services.ghl_auth_service import GHLAuthService

logger = logging.getLogger("passport.ghl_oauth")

router = APIRouter(prefix="/integrations/marketplace", tags=["GHL integration"])


@router.get("/oauth/callback")
def oauth_callback(
    code: Annotated[str, Query(min_length=8, max_length=4096)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    service = GHLAuthService(db, settings)
    try:
        token_payload = service.exchange_code(code)
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

