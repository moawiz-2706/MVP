import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from app.core.config import Settings, get_settings


@dataclass(frozen=True, slots=True)
class SessionPrincipal:
    app_user_id: uuid.UUID
    operator_id: uuid.UUID
    ghl_location_id: str
    role: str
    is_agency_owner: bool


bearer_scheme = HTTPBearer(auto_error=False)


def create_app_session(principal: SessionPrincipal, settings: Settings) -> tuple[str, int]:
    now = datetime.now(UTC)
    lifetime = timedelta(minutes=settings.app_session_minutes)
    token = jwt.encode(
        {
            "sub": str(principal.app_user_id),
            "operator_id": str(principal.operator_id),
            "ghl_location_id": principal.ghl_location_id,
            "role": principal.role,
            "is_agency_owner": principal.is_agency_owner,
            "iat": now,
            "exp": now + lifetime,
            "aud": "passport",
            "iss": "passport-api",
        },
        settings.app_session_secret,
        algorithm="HS256",
    )
    return token, int(lifetime.total_seconds())


def decode_app_session(token: str, settings: Settings) -> SessionPrincipal:
    try:
        claims = jwt.decode(
            token,
            settings.app_session_secret,
            algorithms=["HS256"],
            audience="passport",
            issuer="passport-api",
            options={"require": ["sub", "operator_id", "ghl_location_id", "role", "exp"]},
        )
        return SessionPrincipal(
            app_user_id=uuid.UUID(claims["sub"]),
            operator_id=uuid.UUID(claims["operator_id"]),
            ghl_location_id=claims["ghl_location_id"],
            role=claims["role"],
            is_agency_owner=bool(claims.get("is_agency_owner", False)),
        )
    except (InvalidTokenError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired application session") from exc


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionPrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Application session required")
    return decode_app_session(credentials.credentials, settings)


CurrentPrincipal = Annotated[SessionPrincipal, Depends(get_current_principal)]

