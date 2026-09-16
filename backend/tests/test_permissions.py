import uuid

import pytest
from fastapi import HTTPException

from app.core.app_session import SessionPrincipal
from app.core.permissions import Permission, is_admin, require_permission


def principal(role: str, *, agency_owner: bool = False) -> SessionPrincipal:
    return SessionPrincipal(
        app_user_id=uuid.uuid4(),
        operator_id=uuid.uuid4(),
        ghl_location_id="loc-1",
        role=role,
        is_agency_owner=agency_owner,
    )


def test_spec158_47_admin_and_owner_get_configuration_rights() -> None:
    for actor in (principal("admin"), principal("user", agency_owner=True)):
        assert is_admin(actor)
        for permission in Permission:
            require_permission(actor, permission)  # no raise


def test_spec158_48_ordinary_user_cannot_manage_or_delete() -> None:
    user = principal("user")
    assert not is_admin(user)
    # Ordinary staff may view and operate bookings...
    require_permission(user, Permission.VIEW_BOOKINGS)
    require_permission(user, Permission.OPERATE_BOOKINGS)
    # ...but not configuration, payments, or destructive actions.
    for restricted in (
        Permission.MANAGE_CONFIGURATION,
        Permission.MANAGE_PAYMENTS,
        Permission.DELETE_CONFIGURATION,
    ):
        with pytest.raises(HTTPException) as exc:
            require_permission(user, restricted)
        assert exc.value.status_code == 403


def test_role_matching_is_case_insensitive() -> None:
    assert is_admin(principal("Administrator"))
    assert is_admin(principal("AGENCY_ADMIN"))
