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


def test_remote_user_location_and_role_are_strict() -> None:
    remote = {"locationIds": ["loc-1"], "roles": {"role": "user"}}
    assert GHLStaffUserService._is_same_location_user(remote, "loc-1")
    assert not GHLStaffUserService._is_same_location_user(
        {"locationIds": ["loc-1"], "roles": {"role": "admin"}}, "loc-1"
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
