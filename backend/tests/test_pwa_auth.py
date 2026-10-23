import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.api.v1 import pwa_auth
from app.core.app_session import SessionPrincipal
from app.services.pwa_auth_service import PWAAuthService


def test_pwa_remote_role_accepts_nested_highlevel_role() -> None:
    assert PWAAuthService._remote_role({"roles": {"name": "Administrator"}}) == "administrator"


def test_pwa_remote_location_ids_support_nested_access() -> None:
    assert PWAAuthService._remote_location_ids({"access": {"locationIds": ["loc-1"]}}) == {"loc-1"}


def test_pwa_handoff_stores_only_a_digest_and_short_expiry() -> None:
    rows = []
    service = PWAAuthService.__new__(PWAAuthService)
    service.db = SimpleNamespace(add=rows.append, commit=lambda: None)
    principal = SessionPrincipal(
        app_user_id=uuid.uuid4(),
        operator_id=uuid.uuid4(),
        ghl_location_id="loc-1",
        role="user",
        is_agency_owner=False,
    )

    code = service.create_handoff(principal)

    assert code
    assert len(rows) == 1
    row = rows[0]
    assert row.code_digest != code
    assert len(row.code_digest) == 64
    assert row.app_user_id == principal.app_user_id
    assert row.operator_id == principal.operator_id
    assert row.ghl_location_id == "loc-1"
    assert datetime.now(UTC) < row.expires_at <= datetime.now(UTC) + timedelta(minutes=2, seconds=1)


def test_pwa_session_response_sets_a_host_only_month_long_recovery_cookie() -> None:
    settings = SimpleNamespace(api_prefix="/api/v1", environment="production")

    response = pwa_auth._pwa_session_response(
        "short-lived-api-token",
        "pwa-refresh-only-token",
        31 * 24 * 60 * 60,
        settings,
    )

    cookie = response.headers["set-cookie"]
    assert cookie.startswith("passport_pwa_session=pwa-refresh-only-token;")
    assert "short-lived-api-token" not in cookie
    assert "HttpOnly" in cookie
    assert "Max-Age=2678400" in cookie
    assert "Path=/api/v1/pwa-auth" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie
    assert "Domain=" not in cookie


def test_pwa_refresh_uses_recovery_cookie_when_bearer_token_is_unavailable(monkeypatch) -> None:
    expected = SessionPrincipal(
        app_user_id=uuid.uuid4(),
        operator_id=uuid.uuid4(),
        ghl_location_id="loc-1",
        role="user",
        is_agency_owner=False,
    )
    monkeypatch.setattr(pwa_auth, "decode_pwa_refresh_session", lambda token, settings: expected)
    monkeypatch.setattr(pwa_auth, "validate_session_principal", lambda principal, db: principal)

    principal = pwa_auth._pwa_refresh_principal(
        credentials=None,
        pwa_session="http-only-cookie-token",
        db=object(),
        settings=SimpleNamespace(),
    )

    assert principal == expected
