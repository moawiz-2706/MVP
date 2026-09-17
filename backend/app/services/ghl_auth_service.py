import hashlib
import logging
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.app_session import SessionPrincipal, create_app_session
from app.core.config import Settings
from app.core.encryption import TokenCipher
from app.core.ghl_context import decrypt_ghl_user_context
from app.models.entities import (
    AppUser,
    GHLInstallation,
    GHLOAuthState,
    Operator,
    OperatorSettings,
    OperatorUser,
)

logger = logging.getLogger("passport.ghl_auth")

REQUIRED_SCOPES = {
    "contacts.readonly",
    "contacts.write",
    "conversations/message.write",
    "locations.readonly",
    "calendars.readonly",
    "calendars.write",
    "calendars/events.readonly",
    "calendars/events.write",
}


def required_scopes(settings: Settings) -> set[str]:
    scopes = set(REQUIRED_SCOPES)
    if settings.ghl_staff_user_sync_enabled:
        scopes.update({"users.readonly", "users.write"})
    return scopes


def _slugify(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return result[:140] or "rental-operator"


def _unique_slug(db: Session, name: str, operator_id: uuid.UUID | None = None) -> str:
    base = _slugify(name)
    candidate = base
    suffix = 2
    while db.scalar(
        select(Operator.id).where(
            Operator.slug == candidate,
            Operator.id != operator_id if operator_id else True,
        )
    ):
        candidate = f"{base[:130]}-{suffix}"
        suffix += 1
    return candidate


class GHLAuthService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def create_oauth_state(self, *, expected_location_id: str | None = None) -> str:
        state = secrets.token_urlsafe(32)
        self.db.add(
            GHLOAuthState(
                state_digest=hashlib.sha256(state.encode()).hexdigest(),
                flow="app_start",
                expected_location_id=expected_location_id,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        self.db.commit()
        return state

    def consume_oauth_state(self, state: str) -> GHLOAuthState:
        row = self.db.scalar(
            select(GHLOAuthState)
            .where(GHLOAuthState.state_digest == hashlib.sha256(state.encode()).hexdigest())
            .with_for_update()
        )
        if row is None or row.consumed_at is not None or row.expires_at <= datetime.now(UTC):
            raise ValueError("Invalid or expired HighLevel OAuth state")
        row.consumed_at = datetime.now(UTC)
        self.db.commit()
        return row

    def exchange_code(self, code: str) -> dict[str, Any]:
        response = httpx.post(
            f"{self.settings.ghl_api_base_url.rstrip('/')}/oauth/token",
            data={
                "client_id": self.settings.ghl_client_id,
                "client_secret": self.settings.ghl_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "user_type": "Location",
                "redirect_uri": self.settings.ghl_oauth_redirect_uri,
            },
            headers={"Accept": "application/json", "Version": "v3"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("locationId"):
            raise ValueError(
                "Passport must be installed for a GHL sub-account "
                f"(userType={payload.get('userType')!r}, has_locationId=False, "
                f"has_companyId={bool(payload.get('companyId'))})"
            )
        if str(payload.get("userType", "")).lower() != "location":
            raise ValueError("Passport requires a HighLevel Location token")
        granted = set(str(payload.get("scope", "")).split())
        required = required_scopes(self.settings)
        if not granted or not required.issubset(granted):
            missing = ", ".join(sorted(required - granted))
            raise ValueError(f"Required HighLevel scopes were not granted: {missing}")
        for required in ("access_token", "refresh_token", "userId"):
            if not payload.get(required):
                raise ValueError(f"HighLevel token response is missing {required}")
        return payload

    def fetch_location(self, location_id: str, access_token: str) -> dict[str, Any]:
        response = httpx.get(
            f"{self.settings.ghl_api_base_url.rstrip('/')}/locations/{location_id}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "Version": "2021-07-28",
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("location", payload)

    def provision_installation(
        self, token_payload: dict[str, Any], location: dict[str, Any]
    ) -> Operator:
        location_id = str(token_payload["locationId"])
        operator = self.db.scalar(
            select(Operator).where(Operator.ghl_location_id == location_id).with_for_update()
        )
        name = str(location.get("name") or "Rental Operator")
        timezone = str(location.get("timezone") or "UTC")
        if operator is None:
            operator = Operator(
                ghl_location_id=location_id,
                name=name,
                slug=_unique_slug(self.db, name),
                time_zone=timezone,
            )
            self.db.add(operator)
            self.db.flush()
            self.db.add(OperatorSettings(operator_id=operator.id))
        else:
            operator.name = name
            operator.time_zone = timezone
            operator.is_active = True

        cipher = TokenCipher(self.settings.ghl_token_encryption_key)
        expires = datetime.now(UTC) + timedelta(seconds=int(token_payload.get("expires_in", 86_399)))
        statement = insert(GHLInstallation).values(
            operator_id=operator.id,
            location_id=location_id,
            company_id=token_payload.get("companyId"),
            installed_by_user_id=token_payload.get("userId"),
            access_token_encrypted=cipher.encrypt(token_payload["access_token"]),
            refresh_token_encrypted=cipher.encrypt(token_payload["refresh_token"]),
            access_token_expires_at=expires,
            is_installed=True,
            lifecycle_status="active",
            granted_scopes=list(str(token_payload.get("scope", "")).split()),
            last_verified_at=datetime.now(UTC),
            uninstalled_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[GHLInstallation.location_id],
            set_={
                "operator_id": operator.id,
                "company_id": token_payload.get("companyId"),
                "installed_by_user_id": token_payload.get("userId"),
                "access_token_encrypted": cipher.encrypt(token_payload["access_token"]),
                "refresh_token_encrypted": cipher.encrypt(token_payload["refresh_token"]),
                "access_token_expires_at": expires,
                "is_installed": True,
                "lifecycle_status": "active",
                "authz_version": GHLInstallation.authz_version + 1,
                "generation": GHLInstallation.generation + 1,
                "granted_scopes": list(str(token_payload.get("scope", "")).split()),
                "last_verified_at": datetime.now(UTC),
                "uninstalled_at": None,
                "updated_at": datetime.now(UTC),
            },
        )
        self.db.execute(statement)
        self.db.commit()
        return operator

    def create_session_from_context(self, encrypted_data: str) -> tuple[str, int]:
        context = decrypt_ghl_user_context(encrypted_data, self.settings.ghl_app_shared_secret)
        installation = self.db.scalar(
            select(GHLInstallation).where(
                GHLInstallation.location_id == context.active_location,
                GHLInstallation.is_installed.is_(True),
                GHLInstallation.lifecycle_status == "active",
            )
        )
        if installation is None:
            raise PermissionError("This GHL sub-account has not installed Passport")

        user_statement = insert(AppUser).values(
            ghl_user_id=context.user_id,
            name=context.user_name,
            email=context.email,
        )
        user_statement = user_statement.on_conflict_do_update(
            index_elements=[AppUser.ghl_user_id],
            set_={
                "name": context.user_name,
                "email": context.email,
                "updated_at": datetime.now(UTC),
            },
        ).returning(AppUser.id)
        user_id = self.db.scalar(user_statement)
        if user_id is None:
            raise RuntimeError("Unable to resolve application user")

        membership = insert(OperatorUser).values(
            operator_id=installation.operator_id,
            user_id=user_id,
            ghl_role=context.role,
            is_agency_owner=context.is_agency_owner,
        )
        membership = membership.on_conflict_do_update(
            index_elements=[OperatorUser.operator_id, OperatorUser.user_id],
            set_={
                "ghl_role": context.role,
                "is_agency_owner": context.is_agency_owner,
                "updated_at": datetime.now(UTC),
            },
        )
        self.db.execute(membership)
        self.db.commit()
        return create_app_session(
            SessionPrincipal(
                app_user_id=user_id,
                operator_id=installation.operator_id,
                ghl_location_id=context.active_location,
                role=context.role,
                is_agency_owner=context.is_agency_owner,
                authz_version=installation.authz_version,
            ),
            self.settings,
        )
