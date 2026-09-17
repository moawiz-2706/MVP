from __future__ import annotations

import secrets
import string
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import GHLInstallation, Operator, Staff
from app.services.ghl_client import GHLAPIError, GHLClient

SYNC_PENDING = "pending"
SYNCING = "syncing"
SYNCED = "synced"
NEEDS_PERMISSION_REVIEW = "needs_permission_review"
MANUAL_REVIEW = "manual_review"
SYNC_FAILED = "failed"

# The documented create-user API requires a password, but Passport never stores or
# returns it.  Build it from a CSPRNG and guarantee the special-character rule.
_PASSWORD_SPECIALS = "!@#$%^&*()-_=+[]{}:,.?"


def _temporary_password(length: int = 32) -> str:
    if length < 24:
        raise ValueError("Temporary password must be at least 24 characters")
    chars = [secrets.choice(string.ascii_letters + string.digits) for _ in range(length - 1)]
    chars.append(secrets.choice(_PASSWORD_SPECIALS))
    for index in range(len(chars) - 1, 0, -1):
        swap = secrets.randbelow(index + 1)
        chars[index], chars[swap] = chars[swap], chars[index]
    return "".join(chars)


def _split_name(name: str) -> tuple[str, str]:
    parts = name.strip().split(maxsplit=1)
    first = parts[0] if parts else ""
    return first, parts[1] if len(parts) > 1 else ""


def _remote_location_ids(remote: dict[str, Any]) -> set[str]:
    values: list[Any] = []
    for key in ("locationIds", "location_ids"):
        value = remote.get(key)
        if isinstance(value, list):
            values.extend(value)
    # Some user responses put the location in a nested role/access object.
    for key in ("roles", "role", "access"):
        value = remote.get(key)
        if isinstance(value, dict):
            nested = value.get("locationIds") or value.get("location_ids")
            if isinstance(nested, list):
                values.extend(nested)
    return {str(value) for value in values if value}


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


def _remote_user_id(payload: dict[str, Any]) -> str | None:
    candidate = payload.get("id") or payload.get("userId")
    return str(candidate) if candidate else None


class GHLStaffUserService:
    """Reconcile Passport staff to deliberately least-privileged GHL users.

    This service is called by the durable outbox and by the owner/admin manual
    verification endpoint.  It never logs, persists, or returns the temporary
    password used by GHL's create-user contract.
    """

    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id
        self.settings = get_settings()
        self.client = GHLClient(operator_id)

    def _staff(self, staff_id: uuid.UUID, *, lock: bool = False) -> Staff:
        statement = select(Staff).where(
            Staff.id == staff_id,
            Staff.operator_id == self.operator_id,
            Staff.deleted_at.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        staff = self.db.scalar(statement)
        if staff is None:
            raise NotFoundError("Staff member not found")
        return staff

    def _installation(self) -> tuple[GHLInstallation, Operator]:
        row = self.db.execute(
            select(GHLInstallation, Operator)
            .join(Operator, Operator.id == GHLInstallation.operator_id)
            .where(
                GHLInstallation.operator_id == self.operator_id,
                GHLInstallation.is_installed.is_(True),
                GHLInstallation.lifecycle_status == "active",
            )
        ).one_or_none()
        if row is None:
            raise ConflictError("HighLevel is not installed for this operator")
        installation, operator = row
        if not installation.company_id:
            raise ConflictError("HighLevel installation is missing company ID")
        required = {"users.readonly", "users.write"}
        granted = {str(scope) for scope in (installation.granted_scopes or [])}
        if not required.issubset(granted):
            raise ConflictError("HighLevel users scopes are not granted for this installation")
        return installation, operator

    @staticmethod
    def _least_privilege_permissions() -> dict[str, bool]:
        # All documented module permissions are intentionally disabled.  The
        # owner grants only Calendar/Appointments View in the GHL UI afterwards.
        return {
            "campaignsEnabled": False,
            "campaignsReadOnly": False,
            "contactsEnabled": False,
            "workflowsEnabled": False,
            "workflowsReadOnly": False,
            "triggersEnabled": False,
            "funnelsEnabled": False,
            "websitesEnabled": False,
            "opportunitiesEnabled": False,
            "dashboardStatsEnabled": False,
            "bulkRequestsEnabled": False,
            "appointmentsEnabled": False,
            "reviewsEnabled": False,
            "onlineListingsEnabled": False,
            "phoneCallEnabled": False,
            "conversationsEnabled": False,
            "assignedDataOnly": False,
            "adwordsReportingEnabled": False,
            "membershipEnabled": False,
            "facebookAdsReportingEnabled": False,
            "attributionsReportingEnabled": False,
            "settingsEnabled": False,
            "tagsEnabled": False,
            "leadValueEnabled": False,
            "marketingEnabled": False,
            "agentReportingEnabled": False,
            "botService": False,
            "socialPlanner": False,
            "bloggingEnabled": False,
            "invoiceEnabled": False,
            "affiliateManagerEnabled": False,
            "contentAiEnabled": False,
            "refundsEnabled": False,
            "recordPaymentEnabled": False,
            "cancelSubscriptionEnabled": False,
            "paymentsEnabled": False,
            "communitiesEnabled": False,
            "exportPaymentsEnabled": False,
        }

    @classmethod
    def _is_same_location_user(cls, remote: dict[str, Any], location_id: str) -> bool:
        locations = _remote_location_ids(remote)
        role = _remote_role(remote)
        return location_id in locations and role == "user"

    def _get_remote_user(self, user_id: str, location_id: str) -> dict[str, Any]:
        remote = self.client.request("GET", f"/users/{user_id}", version="v3")
        remote = remote.get("user", remote) if isinstance(remote, dict) else {}
        if not isinstance(remote, dict) or not self._is_same_location_user(remote, location_id):
            raise ConflictError("HighLevel user is not a user in this Passport location")
        return remote

    def _search_exact_email(self, email: str, company_id: str, location_id: str) -> list[dict[str, Any]]:
        result = self.client.request(
            "GET",
            "/users/search",
            # The documented search endpoint remains on the legacy version and
            # supports OAuth/sub-account tokens; the v3 filter-by-email endpoint
            # is agency-token-only.
            version="2021-07-28",
            params={
                "companyId": company_id,
                "locationId": location_id,
                "query": email,
                "limit": 25,
            },
        )
        users = result.get("users", []) if isinstance(result, dict) else []
        return [
            user
            for user in users
            if isinstance(user, dict)
            and str(user.get("email", "")).casefold() == email.casefold()
        ]

    @staticmethod
    def _error_message(exc: Exception) -> str:
        if isinstance(exc, GHLAPIError):
            if exc.status_code in {400, 401, 403, 404, 409, 422}:
                return "HighLevel rejected the staff user request; manual review is required"
            return "HighLevel request outcome is unknown; reconcile the remote user before retrying"
        return "HighLevel request outcome is unknown; reconcile the remote user before retrying"

    def _mark(self, staff: Staff, status: str, error: str | None = None) -> None:
        staff.ghl_user_sync_status = status
        staff.ghl_user_last_error = error[:2000] if error else None
        self.db.flush()

    def sync(self, staff_id: uuid.UUID) -> str | None:
        if not self.settings.ghl_staff_user_sync_enabled:
            return None
        staff = self._staff(staff_id, lock=True)
        if not staff.email:
            self._mark(staff, SYNC_FAILED, "Staff email is required to create a HighLevel user")
            self.db.commit()
            return None
        installation, operator = self._installation()
        email = str(staff.email)
        try:
            if staff.ghl_user_id:
                remote = self._get_remote_user(staff.ghl_user_id, operator.ghl_location_id)
                first_name, last_name = _split_name(staff.name)
                if str(remote.get("email", "")).casefold() != email.casefold():
                    self._mark(staff, MANUAL_REVIEW, "HighLevel user email is immutable; manual linking is required")
                    self.db.commit()
                    return staff.ghl_user_id
                # Do not send permissions/scopes on profile sync: this preserves
                # the owner's granular GHL UI choices after initial provisioning.
                self.client.request(
                    "PUT",
                    f"/users/{staff.ghl_user_id}",
                    version="v3",
                    json={
                        "firstName": first_name,
                        "lastName": last_name,
                        "phone": staff.phone,
                        "type": "account",
                        "role": "user",
                        "locationIds": [operator.ghl_location_id],
                        "companyId": installation.company_id,
                    },
                )
                self._mark(staff, NEEDS_PERMISSION_REVIEW if not staff.ghl_permissions_verified_at else SYNCED)
                self.db.commit()
                return staff.ghl_user_id

            existing = self._search_exact_email(email, installation.company_id, operator.ghl_location_id)
            if existing:
                self._mark(
                    staff,
                    MANUAL_REVIEW,
                    "A HighLevel user already uses this email; automatic linking or password reset is disabled",
                )
                self.db.commit()
                return None

            first_name, last_name = _split_name(staff.name)
            body = {
                "companyId": installation.company_id,
                "email": email,
                "password": _temporary_password(),
                "phone": staff.phone,
                "type": "account",
                "role": "user",
                "locationIds": [operator.ghl_location_id],
                "permissions": self._least_privilege_permissions(),
                "scopes": [],
                "scopesAssignedToOnly": [],
                "firstName": first_name,
                "lastName": last_name,
            }
            result = self.client.request("POST", "/users/", version="v3", json=body)
            remote = result.get("user", result) if isinstance(result, dict) else {}
            remote_id = _remote_user_id(remote) if isinstance(remote, dict) else None
            if not remote_id:
                self._mark(staff, MANUAL_REVIEW, "HighLevel create returned no user ID; manual reconciliation is required")
                self.db.commit()
                return None
            staff.ghl_user_id = remote_id
            self._mark(staff, NEEDS_PERMISSION_REVIEW)
            self.db.commit()
            return remote_id
        except ConflictError:
            raise
        except Exception as exc:
            # A POST can have succeeded even when the response was lost.  Never
            # allow the outbox to blindly repeat it and create a duplicate user.
            self._mark(staff, MANUAL_REVIEW, self._error_message(exc))
            self.db.commit()
            return staff.ghl_user_id

    def verify_permissions(self, staff_id: uuid.UUID, *, confirmed: bool) -> dict[str, Any]:
        if not confirmed:
            raise ConflictError("Explicit permission confirmation is required")
        staff = self._staff(staff_id, lock=True)
        if not staff.ghl_user_id:
            raise ConflictError("Staff has no linked HighLevel user")
        _, operator = self._installation()
        self._get_remote_user(staff.ghl_user_id, operator.ghl_location_id)
        staff.ghl_permissions_verified_at = datetime.now(UTC)
        if staff.ghl_user_sync_status == NEEDS_PERMISSION_REVIEW:
            staff.ghl_user_sync_status = SYNCED
        staff.ghl_user_last_error = None
        self.db.commit()
        return self.payload(staff)

    def verified_active_user_id(self, staff_id: uuid.UUID) -> str | None:
        """Return a GHL ID only after local and current remote checks pass."""
        staff = self._staff(staff_id)
        if (
            not staff.is_active
            or staff.deleted_at is not None
            or not staff.ghl_user_id
            or staff.ghl_permissions_verified_at is None
        ):
            return None
        try:
            _, operator = self._installation()
            self._get_remote_user(staff.ghl_user_id, operator.ghl_location_id)
        except Exception:
            return None
        return staff.ghl_user_id

    @staticmethod
    def payload(staff: Staff) -> dict[str, Any]:
        return {
            "ghl_user_id": staff.ghl_user_id,
            "ghl_user_sync_status": staff.ghl_user_sync_status,
            "ghl_user_last_error": staff.ghl_user_last_error,
            "ghl_permissions_verified_at": staff.ghl_permissions_verified_at,
        }


__all__ = [
    "GHLStaffUserService",
    "MANUAL_REVIEW",
    "NEEDS_PERMISSION_REVIEW",
    "SYNCED",
    "_remote_location_ids",
    "_remote_role",
    "_temporary_password",
]
