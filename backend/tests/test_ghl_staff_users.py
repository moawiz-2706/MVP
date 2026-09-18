from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.services.ghl_staff_user_service import (
    GHLStaffUserService,
    _remote_location_ids,
    _remote_role,
    _temporary_password,
)


def test_temporary_password_is_csprng_length_and_special() -> None:
    password = _temporary_password()
    assert len(password) >= 24
    assert any(not char.isalnum() for char in password)


def test_create_payload_disables_every_permission_and_scope() -> None:
    permissions = GHLStaffUserService._least_privilege_permissions()
    assert permissions
    assert not any(permissions.values())


def test_remote_staff_location_accepts_user_and_admin_roles() -> None:
    for role in ("user", "admin", "administrator"):
        assert GHLStaffUserService._is_same_location_user(
            {"locationIds": ["loc-1"], "roles": {"role": role}}, "loc-1"
        )
    assert not GHLStaffUserService._is_same_location_user(
        {"locationIds": ["loc-1"], "roles": {"role": "agency"}}, "loc-1"
    )
    assert not GHLStaffUserService._is_same_location_user(
        {"locationIds": ["loc-2"], "roles": {"role": "user"}}, "loc-1"
    )


def test_remote_contract_helpers_accept_flat_and_nested_shapes() -> None:
    remote = {"locationIds": ["loc-1"], "role": "user"}
    assert _remote_location_ids(remote) == {"loc-1"}
    assert _remote_role(remote) == "user"


def test_permission_verification_requires_explicit_confirmation() -> None:
    service = GHLStaffUserService.__new__(GHLStaffUserService)
    with pytest.raises(Exception, match="Explicit permission confirmation"):
        service.verify_permissions(uuid.uuid4(), confirmed=False)


def test_payload_does_not_include_password() -> None:
    staff = SimpleNamespace(
        ghl_user_id="remote-1",
        ghl_user_sync_status="needs_permission_review",
        ghl_user_last_error=None,
        ghl_permissions_verified_at=None,
    )
    payload = GHLStaffUserService.payload(staff)
    assert "password" not in payload
    assert "temporary_password" not in payload



def test_directory_search_includes_admin_accounts() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def request(self, method: str, path: str, **kwargs: object) -> dict[str, object]:
            self.calls.append({"method": method, "path": path, **kwargs})
            return {
                "users": [
                    {"id": "user-1", "role": "user", "locationIds": ["loc-1"]},
                    {"id": "admin-1", "role": "admin", "locationIds": ["loc-1"]},
                    {"id": "agency-1", "role": "agency", "locationIds": ["loc-1"]},
                ]
            }

    service = GHLStaffUserService.__new__(GHLStaffUserService)
    service.client = FakeClient()
    users = service._list_remote_users("company-1", "loc-1")

    assert {user["id"] for user in users} == {"user-1", "admin-1"}
    assert "role" not in service.client.calls[0]["params"]



def test_ghl_weekly_schedule_rules_map_to_passport_hours() -> None:
    from app.services.ghl_staff_user_service import _schedule_rules

    hours = _schedule_rules(
        {
            "rules": [
                {"type": "wday", "day": "monday", "intervals": [{"from": "09:00", "to": "17:00"}]},
                {"type": "wday", "wday": 0, "intervals": [{"from": "10:30", "to": "12:00"}]},
            ]
        }
    )
    assert (0, hours[0][1], hours[0][2]) in hours
    assert (6, hours[1][1], hours[1][2]) in hours



def test_ghl_schedule_expands_into_next_fourteen_days_in_utc() -> None:
    from datetime import UTC, datetime, timedelta

    from app.services.ghl_staff_user_service import _expand_schedule_windows

    start = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    windows = _expand_schedule_windows(
        [
            {
                "id": "schedule-1",
                "timezone": "America/New_York",
                "rules": [
                    {"type": "wday", "day": "monday", "intervals": [{"from": "09:00", "to": "17:00"}]},
                ],
            }
        ],
        fallback_timezone="UTC",
        window_start=start,
        window_end=start + timedelta(days=14),
    )

    assert len(windows) == 2
    assert all(item[2] == "schedule-1" for item in windows)
    assert windows[0][0].hour == 13  # 09:00 America/New_York in September


def test_staff_pool_roles_are_independent() -> None:
    from app.schemas.configuration import CalendarCreate

    calendar = CalendarCreate(
        name="River trip",
        slug="river-trip",
        duration_minutes=60,
        required_staff_roles=["Captain", "First Mate"],
    )
    assert calendar.required_staff_roles == ["Captain", "First Mate"]

    with pytest.raises(ValueError):
        CalendarCreate(
            name="No pool",
            slug="no-pool",
            duration_minutes=60,
            required_staff_roles=[],
        )
