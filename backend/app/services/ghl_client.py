import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.encryption import TokenCipher
from app.models.entities import GHLInstallation

logger = logging.getLogger("passport.ghl_api")


class GHLAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, permanent: bool = False):
        self.status_code = status_code
        self.permanent = permanent
        super().__init__(message)


class GHLClient:
    """The only component allowed to make authenticated HighLevel API calls."""

    def __init__(self, operator_id: uuid.UUID, db: Session | None = None) -> None:
        self.operator_id = operator_id
        self.db = db
        self.settings = get_settings()
        self.cipher = TokenCipher(self.settings.ghl_token_encryption_key)

    def _load_token(self, *, force_refresh: bool = False) -> str:
        # Production services pass their existing request/worker session here. This
        # keeps token lookup and refresh on the same connection as the caller rather
        # than opening a second SQLAlchemy session while that caller is active.
        if self.db is not None:
            return self._load_token_from_db(self.db, force_refresh=force_refresh)

        # Keep direct GHLClient usage compatible for scripts and isolated tests.
        with get_session_factory().begin() as db:
            return self._load_token_from_db(db, force_refresh=force_refresh)

    def _load_token_from_db(self, db: Session, *, force_refresh: bool = False) -> str:
        # The FOR UPDATE lock serializes use of rotating refresh tokens.
        installation = db.scalar(
            select(GHLInstallation)
            .where(
                GHLInstallation.operator_id == self.operator_id,
                GHLInstallation.is_installed.is_(True),
            )
            .with_for_update()
        )
        if installation is None:
            raise GHLAPIError("HighLevel is not installed", permanent=True)
        refresh_at = datetime.now(UTC) + timedelta(minutes=5)
        if not force_refresh and installation.access_token_expires_at > refresh_at:
            return self.cipher.decrypt(installation.access_token_encrypted)

        refresh_token = self.cipher.decrypt(installation.refresh_token_encrypted)
        try:
            response = httpx.post(
                f"{self.settings.ghl_api_base_url.rstrip('/')}/oauth/token",
                data={
                    "client_id": self.settings.ghl_client_id,
                    "client_secret": self.settings.ghl_client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "user_type": "Location",
                    "redirect_uri": self.settings.ghl_oauth_redirect_uri,
                },
                headers={"Accept": "application/json", "Version": "v3"},
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            new_access = payload["access_token"]
            new_refresh = payload["refresh_token"]
            expires_in = int(payload.get("expires_in", 86_399))
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            permanent = status in {400, 401, 403}
            if permanent:
                installation.is_installed = False
                installation.uninstalled_at = datetime.now(UTC)
            raise GHLAPIError(
                "Unable to refresh HighLevel authorization",
                status_code=status,
                permanent=permanent,
            ) from exc

        # Both values are replaced atomically because HighLevel rotates refresh tokens.
        installation.access_token_encrypted = self.cipher.encrypt(new_access)
        installation.refresh_token_encrypted = self.cipher.encrypt(new_refresh)
        installation.access_token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        db.flush()
        return new_access

    def request(
        self,
        method: str,
        path: str,
        *,
        version: str = "2021-07-28",
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = self._load_token()
        for attempt in range(2):
            try:
                response = httpx.request(
                    method,
                    f"{self.settings.ghl_api_base_url.rstrip('/')}/{path.lstrip('/')}",
                    params=params,
                    json=json,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Version": version,
                    },
                    timeout=15,
                )
            except httpx.TransportError as exc:
                raise GHLAPIError("HighLevel request failed temporarily") from exc
            if response.status_code == 401 and attempt == 0:
                logger.warning(
                    "HighLevel API returned 401 method=%s path=%s; refreshing token",
                    method,
                    path,
                )
                token = self._load_token(force_refresh=True)
                continue
            if response.is_error:
                try:
                    detail = response.json()
                except ValueError:
                    detail = response.text[:1000]
                logger.error(
                    "HighLevel API failed method=%s path=%s status=%s",
                    method,
                    path,
                    response.status_code,
                )
                raise GHLAPIError(
                    f"HighLevel request failed ({response.status_code}): {detail}",
                    status_code=response.status_code,
                    permanent=response.status_code in {401, 403, 404},
                )
            logger.info(
                "HighLevel API succeeded method=%s path=%s status=%s",
                method,
                path,
                response.status_code,
            )
            return response.json() if response.content else {}
        raise GHLAPIError("HighLevel authorization failed", status_code=401, permanent=True)
