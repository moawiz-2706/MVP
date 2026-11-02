import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core.app_session import SessionPrincipal, validate_session_principal
from app.core.config import Settings
from app.models.entities import AppUser, GHLInstallation, Operator, OperatorUser, PWASession
from app.services.pwa_auth_service import PWAAuthService

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)


@pytest.fixture()
def device(db):
    operator = Operator(ghl_location_id=f"loc-{uuid.uuid4().hex}", name="Op", slug=f"op-{uuid.uuid4().hex[:8]}", time_zone="UTC")
    db.add(operator)
    db.flush()
    db.add(GHLInstallation(operator_id=operator.id, location_id=operator.ghl_location_id, access_token_encrypted="x",
                           refresh_token_encrypted="x", access_token_expires_at=datetime.now(UTC) + timedelta(days=1)))
    user = AppUser(ghl_user_id=f"u-{uuid.uuid4().hex}", email="staff@example.com", name="Staff")
    db.add(user)
    db.flush()
    db.add(OperatorUser(operator_id=operator.id, user_id=user.id, ghl_role="user"))
    db.commit()
    service = PWAAuthService(db, Settings())
    principal = SessionPrincipal(app_user_id=user.id, operator_id=operator.id,
                                 ghl_location_id=operator.ghl_location_id, role="user", is_agency_owner=False)
    _token, _expires, first, rotated = service.refresh_session(principal)  # legacy bearer -> device session
    assert rotated and first.pwa_session_id is not None
    return service, first


def test_racing_refreshes_with_one_cookie_both_succeed_and_only_one_rotates(db, device):
    service, cookie = device
    _t1, _e1, newer, rotated_first = service.refresh_session(validate_session_principal(cookie, db))
    # The second request still carries the cookie the first one just replaced.
    _t2, _e2, same, rotated_second = service.refresh_session(validate_session_principal(cookie, db))

    assert rotated_first and not rotated_second
    assert same.refresh_nonce == cookie.refresh_nonce  # no new cookie is issued for the racer
    validate_session_principal(newer, db)  # the browser's newest cookie stays valid


def test_lost_rotation_response_recovers_instead_of_signing_out(db, device):
    service, held = device
    # The server rotates, but the phone never receives the new cookie.
    _t, _e, undelivered, _ = service.refresh_session(validate_session_principal(held, db))
    session = db.get(PWASession, held.pwa_session_id)
    session.refresh_rotated_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()

    # Minutes later the phone retries with the cookie it still holds.
    _t, _e, recovered, rotated = service.refresh_session(validate_session_principal(held, db))
    assert rotated and recovered.refresh_nonce not in (held.refresh_nonce, undelivered.refresh_nonce)
    validate_session_principal(recovered, db)
    with pytest.raises(HTTPException):
        validate_session_principal(undelivered, db)  # the never-delivered cookie is retired


def test_cookie_two_rotations_old_is_rejected_even_within_grace(db, device):
    service, oldest = device
    _t, _e, middle, _ = service.refresh_session(validate_session_principal(oldest, db))
    service.refresh_session(validate_session_principal(middle, db))

    with pytest.raises(HTTPException):
        validate_session_principal(oldest, db)


def test_revoked_session_rejects_the_grace_cookie_too(db, device):
    service, cookie = device
    service.refresh_session(validate_session_principal(cookie, db))
    session = db.get(PWASession, cookie.pwa_session_id)
    session.revoked_at = datetime.now(UTC)
    db.commit()

    with pytest.raises(HTTPException):
        validate_session_principal(cookie, db)
