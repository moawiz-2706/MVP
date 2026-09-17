import uuid
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.entities import GHLInstallation, Operator, OperatorUser

logger = logging.getLogger("passport.auth")


@dataclass(frozen=True, slots=True)
class SessionPrincipal:
    app_user_id: uuid.UUID
    operator_id: uuid.UUID
    ghl_location_id: str
    role: str
    is_agency_owner: bool
    authz_version: int = 1


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
            "authz_version": principal.authz_version,
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
            authz_version=int(claims.get("authz_version", 1)),
        )
    except (InvalidTokenError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Application session token rejected reason=%s", type(exc).__name__)
        raise HTTPException(status_code=401, detail="Invalid or expired application session") from exc


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Session, Depends(get_db)],
) -> SessionPrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        logger.warning("Application session rejected reason=missing_bearer")
        raise HTTPException(status_code=401, detail="Application session required")
    principal = decode_app_session(credentials.credentials, settings)
    row = db.execute(
        select(GHLInstallation, OperatorUser, Operator)
        .join(OperatorUser, OperatorUser.operator_id == GHLInstallation.operator_id)
        .join(Operator, Operator.id == GHLInstallation.operator_id)
        .where(
            GHLInstallation.operator_id == principal.operator_id,
            GHLInstallation.location_id == principal.ghl_location_id,
            GHLInstallation.is_installed.is_(True),
            GHLInstallation.lifecycle_status == "active",
            Operator.is_active.is_(True),
            OperatorUser.user_id == principal.app_user_id,
        )
    ).one_or_none()
    if row is None:
        logger.warning(
            "Application session rejected reason=installation_membership_mismatch operator_id=%s location_id=%s user_id=%s",
            principal.operator_id,
            principal.ghl_location_id,
            principal.app_user_id,
        )
        raise HTTPException(status_code=401, detail="Application session is no longer valid")
    installation, membership, _operator = row
    if installation.authz_version != principal.authz_version:
        logger.warning(
            "Application session rejected reason=authz_version_mismatch operator_id=%s token_version=%s current_version=%s",
            principal.operator_id,
            principal.authz_version,
            installation.authz_version,
        )
        raise HTTPException(status_code=401, detail="Application session requires refresh")
    return SessionPrincipal(
        app_user_id=principal.app_user_id,
        operator_id=principal.operator_id,
        ghl_location_id=principal.ghl_location_id,
        role=membership.ghl_role or principal.role,
        is_agency_owner=membership.is_agency_owner,
        authz_version=installation.authz_version,
    )


CurrentPrincipal = Annotated[SessionPrincipal, Depends(get_current_principal)]
