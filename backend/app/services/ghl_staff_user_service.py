from __future__ import annotations

import secrets
import string
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import GHLInstallation, Operator, Staff, StaffAvailabilityWindow, StaffHour
from app.services.ghl_client import GHLAPIError, GHLClient
from app.utils.timezone import require_timezone, wall_time_exists

SYNC_PENDING = "pending"
SYNCING = "syncing"
SYNCED = "synced"
NEEDS_PERMISSION_REVIEW = "needs_permission_review"
MANUAL_REVIEW = "manual_review"
SYNC_FAILED = "failed"
SYNC_REMOVED = "removed"

_DAY_NAMES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _parse_clock(value: Any) -> time | None:
    if not isinstance(value, str):
        return None
    try:
        parts = value.strip().split(":")
        if len(parts) not in {2, 3}:
            return None
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
        return time(hour=hour, minute=minute, second=second)
    except (TypeError, ValueError):
        return None


def _schedule_rules(schedule: dict[str, Any]) -> list[tuple[int, time, time]]:
    rules = schedule.get("rules") or schedule.get("availabilityRules") or []
    if not isinstance(rules, list):
        return []
    parsed: set[tuple[int, time, time]] = set()
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("type") not in {None, "wday"}:
            continue
        day_value = str(rule.get("day") or "").strip().casefold()
        day = _DAY_NAMES.get(day_value)
        if day is None:
            try:
                # GHL's numeric weekday representation is Sunday=0.
                day = (int(rule.get("wday")) - 1) % 7
            except (TypeError, ValueError):
                continue
        intervals = rule.get("intervals") or []
        if not isinstance(intervals, list):
            continue
        for interval in intervals:
            if not isinstance(interval, dict):
                continue
            start, end = _parse_clock(interval.get("from")), _parse_clock(interval.get("to"))
            if start and end and start < end:
                parsed.add((day, start, end))
    return sorted(parsed, key=lambda item: (item[0], item[1], item[2]))


def _expand_schedule_windows(
    schedules: list[dict[str, Any]],
    *,
    fallback_timezone: str,
    window_start: datetime,
    window_end: datetime,
) -> list[tuple[datetime, datetime, str | None]]:
    windows: set[tuple[datetime, datetime, str | None]] = set()
    for schedule in schedules:
        timezone_name = str(schedule.get("timezone") or schedule.get("timeZone") or fallback_timezone)
        zone = require_timezone(timezone_name)
        rules = _schedule_rules(schedule)
        local_start = window_start.astimezone(zone).date() - timedelta(days=1)
        local_end = window_end.astimezone(zone).date() + timedelta(days=1)
        current = local_start
        schedule_id = schedule.get("_schedule_id") or schedule.get("id") or schedule.get("scheduleId")
        while current <= local_end:
            for day, opens, closes in rules:
                if current.weekday() != day:
                    continue
                local_open = datetime.combine(current, opens, tzinfo=zone)
                local_close = datetime.combine(current, closes, tzinfo=zone)
                if not wall_time_exists(local_open) or not wall_time_exists(local_close):
                    continue
                start_at = max(local_open.astimezone(UTC), window_start)
                end_at = min(local_close.astimezone(UTC), window_end)
                if start_at < end_at:
                    windows.add((start_at, end_at, str(schedule_id) if schedule_id else None))
            current += timedelta(days=1)
    return sorted(windows, key=lambda item: (item[0], item[1], item[2] or ""))

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
        self.client = GHLClient(operator_id, db)

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

    def _installation(
        self, required_scopes: set[str] | None = None
    ) -> tuple[GHLInstallation, Operator]:
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
        required = required_scopes or {"users.readonly"}
        granted = {str(scope) for scope in (installation.granted_scopes or [])}
        if not required.issubset(granted):
            missing = ", ".join(sorted(required - granted))
            raise ConflictError(f"HighLevel users scopes are not granted: {missing}")
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
        return location_id in locations and role in {"user", "admin", "administrator"}

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
            and self._is_same_location_user(user, location_id)
        ]

    def _list_remote_users(self, company_id: str, location_id: str) -> list[dict[str, Any]]:
        """List account-level users in this installed sub-account.

        HighLevel's OAuth-compatible search endpoint is paginated. Do not send
        role=user here because that excludes sub-account administrators. Keep
        the final location/role filter locally as a tenant-safety boundary.
        """
        users: list[dict[str, Any]] = []
        skip = 0
        page_size = 100
        while skip < 1000:
            result = self.client.request(
                "GET",
                "/users/search",
                version="2021-07-28",
                params={
                    "companyId": company_id,
                    "locationId": location_id,
                    "type": "account",
                    "skip": skip,
                    "limit": page_size,
                },
            )
            page = result.get("users", []) if isinstance(result, dict) else []
            page = [user for user in page if isinstance(user, dict)]
            users.extend(
                user
                for user in page
                if self._is_same_location_user(user, location_id)
            )
            if len(page) < page_size:
                break
            skip += page_size
        return users

    def _user_schedules(self, location_id: str, user_id: str) -> list[dict[str, Any]]:
        result = self.client.request(
            "GET",
            "/calendars/schedules/search",
            version="2023-02-21",
            params={"locationId": location_id, "userId": user_id, "skip": 0, "limit": 500},
        )
        summaries = result.get("schedules", []) if isinstance(result, dict) else []
        if not isinstance(summaries, list):
            return []
        schedules: list[dict[str, Any]] = []
        for summary in summaries:
            if not isinstance(summary, dict):
                continue
            schedule_id = summary.get("id") or summary.get("scheduleId")
            if schedule_id:
                detail = self.client.request(
                    "GET", f"/calendars/schedules/{schedule_id}", version="v3"
                )
                detail = detail.get("schedule", detail) if isinstance(detail, dict) else {}
                if isinstance(detail, dict):
                    detail["_schedule_id"] = str(schedule_id)
                    schedules.append(detail)
            else:
                schedules.append(summary)
        return schedules

    @staticmethod
    def _safe_profile(remote: dict[str, Any]) -> dict[str, Any]:
        blocked = ("password", "token", "secret", "authorization", "refresh")

        def clean(value: Any, key: str = "") -> Any:
            if any(word in key.casefold() for word in blocked):
                return None
            if isinstance(value, dict):
                return {str(k): clean(v, str(k)) for k, v in value.items() if clean(v, str(k)) is not None}
            if isinstance(value, list):
                return [clean(item, key) for item in value]
            return value

        return clean(remote)

    def sync_availability(self, staff_id: uuid.UUID) -> dict[str, Any]:
        staff = self._staff(staff_id, lock=True)
        if not staff.ghl_user_id:
            raise ConflictError("Staff has no linked HighLevel user")
        try:
            _, operator = self._installation({"users.readonly", "calendars.readonly"})
            remote = self._get_remote_user(staff.ghl_user_id, operator.ghl_location_id)
            schedules = self._user_schedules(operator.ghl_location_id, staff.ghl_user_id)
            hours: set[tuple[int, time, time]] = set()
            time_zone = None
            for schedule in schedules:
                time_zone = time_zone or schedule.get("timezone") or schedule.get("timeZone")
                hours.update(_schedule_rules(schedule))
            effective_timezone = str(time_zone or operator.time_zone)
            window_start = datetime.now(UTC)
            window_end = window_start + timedelta(days=14)
            windows = _expand_schedule_windows(
                schedules,
                fallback_timezone=effective_timezone,
                window_start=window_start,
                window_end=window_end,
            )
            self.db.execute(delete(StaffHour).where(StaffHour.staff_id == staff.id))
            self.db.add_all(
                StaffHour(staff_id=staff.id, day_of_week=day, start_time=start, end_time=end)
                for day, start, end in sorted(hours)
            )
            self.db.execute(
                delete(StaffAvailabilityWindow).where(StaffAvailabilityWindow.staff_id == staff.id)
            )
            self.db.add_all(
                StaffAvailabilityWindow(
                    staff_id=staff.id,
                    start_at=start_at,
                    end_at=end_at,
                    source_schedule_id=schedule_id,
                )
                for start_at, end_at, schedule_id in windows
            )
            staff.availability_time_zone = effective_timezone
            staff.availability_sync_status = SYNCED
            staff.availability_last_error = None
            staff.availability_last_synced_at = datetime.now(UTC)
            self.db.commit()
            return {
                "profile": self._safe_profile(remote),
                "time_zone": staff.availability_time_zone,
                "hours": sorted(hours),
                "window_start": window_start,
                "window_end": window_end,
                "window_count": len(windows),
            }
        except Exception as exc:
            staff.availability_sync_status = SYNC_FAILED
            staff.availability_last_error = str(exc)[:2000]
            self.db.commit()
            raise

    def details(self, staff_id: uuid.UUID) -> dict[str, Any]:
        staff = self._staff(staff_id)
        result = self.sync_availability(staff.id)
        return {
            "staff_id": staff.id,
            "ghl_user_id": staff.ghl_user_id,
            "profile": result["profile"],
            "time_zone": staff.availability_time_zone,
            "hours": [
                {"day_of_week": day, "start_time": start, "end_time": end}
                for day, start, end in result["hours"]
            ],
            "window_start": result["window_start"],
            "window_end": result["window_end"],
            "window_count": result["window_count"],
            "availability_sync_status": staff.availability_sync_status,
            "availability_last_synced_at": staff.availability_last_synced_at,
        }

    def sync_all_availability(self) -> dict[str, int | str | None]:
        """Refresh every linked staff member for this operator.

        This is called by the protected daily cron. It intentionally reconciles
        only availability; it does not modify any GHL user profile or permission.
        """
        staff_ids = list(
            self.db.scalars(
                select(Staff.id).where(
                    Staff.operator_id == self.operator_id,
                    Staff.deleted_at.is_(None),
                    Staff.is_active.is_(True),
                    Staff.ghl_user_id.is_not(None),
                )
            )
        )
        synced = failed = 0
        last_error: str | None = None
        for staff_id in staff_ids:
            try:
                self.sync_availability(staff_id)
                synced += 1
            except Exception as exc:
                failed += 1
                last_error = str(exc)[:2000]
        return {"synced": synced, "failed": failed, "error": last_error}

    @staticmethod
    def _remote_profile(remote: dict[str, Any]) -> tuple[str, str | None, str | None]:
        first = str(remote.get("firstName") or "").strip()
        last = str(remote.get("lastName") or "").strip()
        name = str(remote.get("name") or " ".join(part for part in (first, last) if part)).strip()
        email = str(remote.get("email") or "").strip().lower() or None
        phone = str(remote.get("phone") or "").strip() or None
        return name or email or "GHL Staff", email, phone

    def sync_directory(self) -> dict[str, int | str | None]:
        """Import all existing GHL account users into the local staff roster.

        This deliberately never creates a remote user. Passport stores the GHL
        user ID and uses it for appointment assignment; operational roles remain
        per-booking StaffAssignment.role so one person can have different roles
        on different bookings.
        """
        if not self.settings.ghl_staff_user_sync_enabled:
            raise ConflictError("GHL staff directory sync is disabled")
        installation, operator = self._installation({"users.readonly"})
        remote_users = self._list_remote_users(installation.company_id, operator.ghl_location_id)
        local_staff = list(
            self.db.scalars(
                select(Staff).where(
                    Staff.operator_id == self.operator_id,
                    Staff.deleted_at.is_(None),
                )
            )
        )
        by_ghl_id = {staff.ghl_user_id: staff for staff in local_staff if staff.ghl_user_id}
        by_email = {
            str(staff.email).casefold(): staff
            for staff in local_staff
            if staff.email and not staff.ghl_user_id
        }
        created = updated = deactivated = 0
        seen_remote_ids: set[str] = set()
        for remote in remote_users:
            remote_id = _remote_user_id(remote)
            if not remote_id:
                continue
            seen_remote_ids.add(remote_id)
            name, email, phone = self._remote_profile(remote)
            staff = by_ghl_id.get(remote_id) or (by_email.get(email.casefold()) if email else None)
            if staff is None:
                staff = Staff(
                    operator_id=self.operator_id,
                    name=name,
                    email=email,
                    phone=phone,
                    is_active=not bool(remote.get("deleted")),
                    ghl_user_id=remote_id,
                    ghl_user_sync_status=NEEDS_PERMISSION_REVIEW,
                )
                self.db.add(staff)
                created += 1
            else:
                staff.ghl_user_id = remote_id
                staff.name = name
                staff.email = email
                staff.phone = phone
                staff.is_active = not bool(remote.get("deleted"))
                if staff.ghl_user_sync_status in {
                    "not_requested",
                    SYNC_FAILED,
                    MANUAL_REVIEW,
                    SYNC_REMOVED,
                }:
                    staff.ghl_user_sync_status = NEEDS_PERMISSION_REVIEW
                updated += 1
            by_ghl_id[remote_id] = staff

        # The list response is authoritative only after the complete paginated
        # request succeeds. Keep historical rows for bookings, but make users
        # missing from GHL unavailable for new bookings and remove stale cache
        # rows so old schedules cannot continue to open booking slots.
        for staff in local_staff:
            if staff.ghl_user_id and staff.ghl_user_id not in seen_remote_ids:
                if staff.is_active or staff.availability_sync_status != SYNC_REMOVED:
                    deactivated += 1
                staff.is_active = False
                staff.availability_sync_status = SYNC_REMOVED
                staff.availability_last_error = (
                    "HighLevel no longer returns this user for the installed sub-account"
                )
                staff.availability_last_synced_at = datetime.now(UTC)
                staff.ghl_user_sync_status = SYNC_REMOVED
                self.db.execute(delete(StaffHour).where(StaffHour.staff_id == staff.id))
                self.db.execute(
                    delete(StaffAvailabilityWindow).where(
                        StaffAvailabilityWindow.staff_id == staff.id
                    )
                )

        self.db.commit()
        availability_failed = 0
        availability_synced = 0
        for staff in by_ghl_id.values():
            if not staff.is_active:
                continue
            try:
                self.sync_availability(staff.id)
                availability_synced += 1
            except Exception:
                availability_failed += 1
        return {
            "synced": created + updated,
            "created": created,
            "updated": updated,
            "deactivated": deactivated,
            "availability_synced": availability_synced,
            "availability_failed": availability_failed,
            "error": None,
        }

    def sync_all(self) -> dict[str, int | str | None]:
        """Reconcile the complete GHL directory and cached availability."""
        if not self.settings.ghl_staff_user_sync_enabled:
            raise ConflictError("GHL staff directory sync is disabled")
        result = self.sync_directory()
        return result

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
        installation, operator = self._installation({"users.readonly"})
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
            remote_id = _remote_user_id(existing[0]) if len(existing) == 1 else None
            if not remote_id:
                message = (
                    "No matching HighLevel account user was found; add the user in HighLevel "
                    "and sync the staff directory"
                    if not existing
                    else "Multiple HighLevel users match this email; manual reconciliation is required"
                )
                self._mark(staff, MANUAL_REVIEW, message)
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
    "SYNC_REMOVED",
    "SYNCED",
    "_remote_location_ids",
    "_remote_role",
    "_temporary_password",
]
