from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.app_session import SessionPrincipal, create_app_session
from app.core.config import Settings
from app.core.encryption import TokenCipher
from app.models.entities import AppUser, GHLInstallation, Operator, OperatorUser, PWAAuthHandoff

logger = logging.getLogger("passport.pwa_auth")


class PWAAuthService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def login_with_highlevel(
        self,
        token_payload: dict[str, Any],
        *,
        expected_location_id: str | None = None,
    ) -> SessionPrincipal:
        location_id = str(token_payload["locationId"])
        if expected_location_id and location_id != expected_location_id:
            raise ValueError("HighLevel location does not match the requested Passport location")

        installation = self.db.scalar(
            select(GHLInstallation).where(
                GHLInstallation.location_id == location_id,
                GHLInstallation.is_installed.is_(True),
                GHLInstallation.lifecycle_status == "active",
            )
        )
        if installation is None:
            raise ValueError("This HighLevel location has not installed Passport")
        operator = self.db.get(Operator, installation.operator_id)

        if operator is None or installation is None or not operator.is_active:
            raise ValueError("This HighLevel location is not available in Passport")

        remote_user = self._fetch_user(
            token_payload["userId"], location_id, token_payload["access_token"]
        )
        role = self._remote_role(remote_user)
        if role not in {"user", "admin", "administrator"}:
            raise ValueError("This HighLevel user cannot access Passport")

        user_id = self._upsert_user(remote_user, str(token_payload["userId"]))
        self._upsert_membership(
            operator.id,
            user_id,
            role=role,
            is_agency_owner=False,
        )
        cipher = TokenCipher(self.settings.ghl_token_encryption_key)
        installation.access_token_encrypted = cipher.encrypt(token_payload["access_token"])
        installation.refresh_token_encrypted = cipher.encrypt(token_payload["refresh_token"])
        installation.access_token_expires_at = datetime.now(UTC) + timedelta(
            seconds=int(token_payload.get("expires_in", 86_399))
        )
        installation.installed_by_user_id = str(token_payload["userId"])
        installation.granted_scopes = list(str(token_payload.get("scope", "")).split())
        installation.last_verified_at = datetime.now(UTC)
        self.db.commit()
        return SessionPrincipal(
            app_user_id=user_id,
            operator_id=operator.id,
            ghl_location_id=location_id,
            role=role,
            is_agency_owner=False,
            authz_version=installation.authz_version,
        )

    def create_handoff(self, principal: SessionPrincipal) -> str:
        code = secrets.token_urlsafe(32)
        self.db.add(
            PWAAuthHandoff(
                code_digest=hashlib.sha256(code.encode()).hexdigest(),
                app_user_id=principal.app_user_id,
                operator_id=principal.operator_id,
                ghl_location_id=principal.ghl_location_id,
                expires_at=datetime.now(UTC) + timedelta(minutes=2),
            )
        )
        self.db.commit()
        return code

    def exchange_handoff(self, code: str) -> tuple[str, int]:
        handoff = self.db.scalar(
            select(PWAAuthHandoff)
            .where(PWAAuthHandoff.code_digest == hashlib.sha256(code.encode()).hexdigest())
            .with_for_update()
        )
        now = datetime.now(UTC)
        if handoff is None or handoff.consumed_at is not None or handoff.expires_at <= now:
            raise ValueError("Invalid or expired PWA login handoff")
        installation = self.db.scalar(
            select(GHLInstallation).where(
                GHLInstallation.operator_id == handoff.operator_id,
                GHLInstallation.location_id == handoff.ghl_location_id,
                GHLInstallation.is_installed.is_(True),
                GHLInstallation.lifecycle_status == "active",
            )
        )
        membership = self.db.scalar(
            select(OperatorUser).where(
                OperatorUser.operator_id == handoff.operator_id,
                OperatorUser.user_id == handoff.app_user_id,
            )
        )
        operator = self.db.get(Operator, handoff.operator_id)
        if installation is None or membership is None or operator is None or not operator.is_active:
            raise ValueError("This Passport session is no longer valid")
        handoff.consumed_at = now
        self.db.commit()
        return create_app_session(
            SessionPrincipal(
                app_user_id=handoff.app_user_id,
                operator_id=handoff.operator_id,
                ghl_location_id=handoff.ghl_location_id,
                role=membership.ghl_role or "user",
                is_agency_owner=membership.is_agency_owner,
                authz_version=installation.authz_version,
            ),
            self.settings,
        )

    def refresh_session(self, principal: SessionPrincipal) -> tuple[str, int]:
        installation = self.db.scalar(
            select(GHLInstallation).where(
                GHLInstallation.operator_id == principal.operator_id,
                GHLInstallation.location_id == principal.ghl_location_id,
                GHLInstallation.is_installed.is_(True),
                GHLInstallation.lifecycle_status == "active",
            )
        )
        membership = self.db.scalar(
            select(OperatorUser).where(
                OperatorUser.operator_id == principal.operator_id,
                OperatorUser.user_id == principal.app_user_id,
            )
        )
        operator = self.db.get(Operator, principal.operator_id)
        if installation is None or membership is None or operator is None or not operator.is_active:
            raise ValueError("Passport session is no longer valid")
        role = membership.ghl_role or principal.role
        return create_app_session(
            SessionPrincipal(
                app_user_id=principal.app_user_id,
                operator_id=principal.operator_id,
                ghl_location_id=principal.ghl_location_id,
                role=role,
                is_agency_owner=membership.is_agency_owner,
                authz_version=installation.authz_version,
            ),
            self.settings,
        )

    def _fetch_user(self, user_id: str, location_id: str, access_token: str) -> dict[str, Any]:
        response = httpx.get(
            f"{self.settings.ghl_api_base_url.rstrip('/')}/users/{user_id}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "Version": "v3",
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        remote = payload.get("user", payload) if isinstance(payload, dict) else {}
        if not isinstance(remote, dict):
            raise ValueError("HighLevel did not return a valid user")
        locations = self._remote_location_ids(remote)
        if locations and location_id not in locations:
            raise ValueError("HighLevel user does not belong to this location")
        return remote

    def _upsert_user(self, remote: dict[str, Any], fallback_id: str):
        name = str(remote.get("name") or remote.get("firstName") or "HighLevel user")
        if remote.get("lastName") and remote.get("firstName"):
            name = f"{remote['firstName']} {remote['lastName']}".strip()
        statement = insert(AppUser).values(
            ghl_user_id=fallback_id,
            name=name,
            email=remote.get("email"),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[AppUser.ghl_user_id],
            set_={"name": name, "email": remote.get("email")},
        ).returning(AppUser.id)
        user_id = self.db.scalar(statement)
        if user_id is None:
            raise RuntimeError("Unable to create the Passport user session")
        return user_id

    def _upsert_membership(
        self,
        operator_id,
        user_id,
        *,
        role: str,
        is_agency_owner: bool,
    ) -> None:
        statement = insert(OperatorUser).values(
            operator_id=operator_id,
            user_id=user_id,
            ghl_role=role,
            is_agency_owner=is_agency_owner,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[OperatorUser.operator_id, OperatorUser.user_id],
            set_={"ghl_role": role, "is_agency_owner": is_agency_owner},
        )
        self.db.execute(statement)

    @staticmethod
    def _remote_role(remote: dict[str, Any]) -> str:
        role = remote.get("role")
        if isinstance(role, str) and role.strip():
            return role.strip().casefold()
        roles = remote.get("roles")
        if isinstance(roles, dict):
            for key in ("role", "name", "type"):
                value = roles.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip().casefold()
        return ""

    @staticmethod
    def _remote_location_ids(remote: dict[str, Any]) -> set[str]:
        values: list[Any] = []
        for key in ("locationIds", "location_ids"):
            value = remote.get(key)
            if isinstance(value, list):
                values.extend(value)
        for key in ("roles", "role", "access"):
            value = remote.get(key)
            if isinstance(value, dict):
                nested = value.get("locationIds") or value.get("location_ids")
                if isinstance(nested, list):
                    values.extend(nested)
        return {str(value) for value in values if value}
