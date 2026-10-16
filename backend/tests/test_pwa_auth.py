import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

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
