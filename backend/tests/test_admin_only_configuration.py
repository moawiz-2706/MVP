"""Calendars, resources, locations, staff and roles, and settings are admin-only."""

import asyncio
import importlib
import inspect
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.core.app_session import SessionPrincipal
from app.core.config import Settings

# (module, method, path) for every change an admin alone may make. GETs that
# booking screens need (calendar and resource lists) stay open to all staff.
ADMIN_ROUTES = [
    *[("configuration", method, path) for method, path in (
        ("POST", "/locations"), ("PATCH", "/locations/{entity_id}"), ("DELETE", "/locations/{entity_id}"),
        ("POST", "/resources"), ("PATCH", "/resources/{entity_id}"), ("DELETE", "/resources/{entity_id}"),
        ("POST", "/customer-types"), ("PATCH", "/customer-types/{entity_id}"), ("DELETE", "/customer-types/{entity_id}"),
        ("POST", "/calendar-categories"), ("PATCH", "/calendar-categories/{entity_id}"),
        ("DELETE", "/calendar-categories/{entity_id}"),
        ("POST", "/calendars"), ("PATCH", "/calendars/{entity_id}"), ("DELETE", "/calendars/{entity_id}"),
        ("PUT", "/calendars/{calendar_id}/hours"), ("PUT", "/calendars/{calendar_id}/date-hours"),
        ("POST", "/calendars/{calendar_id}/pushed-slots"),
        ("DELETE", "/calendars/{calendar_id}/pushed-slots/{slot_id}"),
        ("PUT", "/calendars/{calendar_id}/blocks"), ("POST", "/calendars/{calendar_id}/blocks"),
        ("PATCH", "/calendars/{calendar_id}/blocks/{block_id}"),
        ("DELETE", "/calendars/{calendar_id}/blocks/{block_id}"),
        ("PUT", "/calendars/{calendar_id}/resources"), ("PUT", "/calendars/{calendar_id}/rates"),
        ("DELETE", "/calendars/{calendar_id}/rates/{customer_type_id}"),
    )],
    ("partners", "POST", "/partners"),
    ("partners", "PATCH", "/partners/{partner_id}"),
    ("partners", "DELETE", "/partners/{partner_id}"),
    ("partners", "GET", "/reports/partner-commissions"),
    ("fareharbor_replica", "PUT", "/calendars/{calendar_id}/booking-policy"),
    ("fareharbor_replica", "POST", "/booking-custom-fields"),
    ("fareharbor_replica", "PATCH", "/booking-custom-fields/{field_id}"),
    ("fareharbor_replica", "DELETE", "/booking-custom-fields/{field_id}"),
    ("staff", "POST", "/staff"),
    ("staff", "PATCH", "/staff/{staff_id}"),
    ("staff", "PATCH", "/staff/{staff_id}/custom-role"),
    ("staff", "DELETE", "/staff/{staff_id}"),
    ("staff", "POST", "/staff/{staff_id}/booking-link"),
    ("staff_ghl", "POST", "/staff-ghl/directory/sync"),
    ("messages", "PUT", "/settings/messages/{event_type}"),
    ("messages", "DELETE", "/settings/messages/{event_type}"),
    ("waivers", "PUT", "/settings/waiver"),
    ("stripe_connect", "POST", "/settings/payments/stripe/connect"),
    ("stripe_connect", "POST", "/settings/payments/stripe/onboarding-link"),
]


def _principal(role: str) -> SessionPrincipal:
    return SessionPrincipal(
        app_user_id=uuid.uuid4(), operator_id=uuid.uuid4(), ghl_location_id="loc",
        role=role, is_agency_owner=False,
    )


def _endpoint(module: str, method: str, path: str):
    router = importlib.import_module(f"app.api.v1.{module}").router
    for route in router.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", ()):
            return route.endpoint
    raise AssertionError(f"{method} {path} not found in {module}")


def _call(endpoint, principal, db):
    kwargs = {}
    for name in inspect.signature(endpoint).parameters:
        if name == "principal":
            kwargs[name] = principal
        elif name == "db":
            kwargs[name] = db
        elif name == "settings":
            kwargs[name] = Settings()
        elif name.endswith("_id"):
            kwargs[name] = uuid.uuid4()
        else:
            kwargs[name] = MagicMock()
    result = endpoint(**kwargs)
    if inspect.iscoroutine(result):
        asyncio.run(result)


@pytest.mark.parametrize("module,method,path", ADMIN_ROUTES, ids=[f"{m} {p}" for _, m, p in ADMIN_ROUTES])
def test_non_admin_is_refused_before_anything_changes(module, method, path):
    db = MagicMock()
    with pytest.raises(HTTPException) as refused:
        _call(_endpoint(module, method, path), _principal("user"), db)
    assert refused.value.status_code == 403
    db.commit.assert_not_called()
    db.add.assert_not_called()
    db.execute.assert_not_called()


@pytest.mark.parametrize("role", ["admin", "Administrator", "agency_admin"])
def test_admin_roles_pass_the_guard(role):
    from app.api.v1.configuration import require_admin

    require_admin(_principal(role))
    require_admin(_principal(role), delete=True)


def test_bootstrap_hides_admin_pages_and_role_badge_from_non_admins(monkeypatch):
    from app.services import pwa_workspace_service
    from app.services.pwa_workspace_service import PWAWorkspaceService

    def bootstrap(role):
        db = MagicMock()
        db.scalar.return_value = 3  # three staff without a role, no sync failures
        service = PWAWorkspaceService(db, _principal(role))
        monkeypatch.setattr(service, "_identity", lambda: (MagicMock(), MagicMock(), MagicMock()))
        monkeypatch.setattr(service, "_me", lambda *args: (None, None))
        monkeypatch.setattr(pwa_workspace_service, "PWABootstrapResponse", lambda **kwargs: kwargs)
        return service.bootstrap()

    user = bootstrap("user")
    assert user["features"]["calendar_management"] is False
    assert user["features"]["staff_management"] is False
    assert user["features"]["settings"] is False
    assert "manage_configuration" not in user["permissions"]
    assert user["badge_counts"].staff_missing_roles == 0

    admin = bootstrap("admin")
    assert admin["features"]["staff_management"] is True
    assert "manage_configuration" in admin["permissions"]
    assert admin["badge_counts"].staff_missing_roles == 3


def test_calendar_setup_notifications_are_for_admins_only(monkeypatch):
    from app.services.notification_service import NotificationService

    service = NotificationService(MagicMock(), uuid.uuid4())
    service.db.scalars.return_value = [MagicMock(id=uuid.uuid4())]
    called = []
    monkeypatch.setattr(service, "_calendar_items", lambda calendars: called.append(True) or [])
    monkeypatch.setattr(service, "_ghl_sync_items", lambda: [])
    service.list(include_configuration=False)
    assert called == []
    service.list(include_configuration=True)
    assert called == [True]
