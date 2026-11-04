"""Staff can ask for one waiver per guest; customers keep one per party."""

import base64
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import ConflictError
from app.models.entities import BookingParticipant
from app.schemas.order import OrderCreateRequest
from app.schemas.waiver import WaiverSignRequest
from app.services import waiver_service as module
from app.services.waiver_service import WaiverService

ADDRESS = {"street": "1 Dock St", "city": "Punta Gorda", "state": "FL", "postal_code": "33950", "country": "US"}
PNG = "data:image/png;base64," + base64.b64encode(bytes.fromhex("89504e470d0a1a0a") + bytes(16)).decode()


def _adult(first="Alex", born=date(1990, 1, 1)):
    return {"first_name": first, "last_name": "Smith", "date_of_birth": born.isoformat(),
            "email": f"{first.lower()}@example.com", "phone": "+15555550100"}


def _request(signer, participants=()):
    return WaiverSignRequest(signer=signer, address=ADDRESS, participants=list(participants),
                             signature_png=PNG, opt_in=False, agreed=True)


def _service(monkeypatch, *, mode, units=3):
    start = datetime.now(UTC) + timedelta(days=10)
    waiver = SimpleNamespace(id=uuid.uuid4(), status="pending", guest_number=2, public_expires_at=None,
                             created_at=datetime.now(UTC), details=None, token="t")
    booking = SimpleNamespace(id=uuid.uuid4(), operator_id=uuid.uuid4(), booking_order_id=uuid.uuid4(), units=units,
                              status="confirmed", start_at=start, end_at=start + timedelta(hours=2),
                              calendar_name_snapshot="Sunset Cruise")
    order = SimpleNamespace(id=booking.booking_order_id, waiver_mode=mode, customer_first_name="Lead",
                            customer_last_name="Booker", customer_email="lead@example.com", customer_phone=None)
    operator = SimpleNamespace(name="PGA", time_zone="America/New_York")
    settings = SimpleNamespace(waiver_text="Release", waiver_title="Waiver", waiver_opt_in_label=None, waiver_website=None)
    db = MagicMock()
    db.scalars.return_value = []
    service = WaiverService(db)
    monkeypatch.setattr(service, "_row", lambda token, lock=False: (waiver, booking, order, operator, settings))
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(
        waiver_public_days=30, ghl_booking_record_sync_enabled=False, ghl_sync_mode="disabled", frontend_url="https://p"))
    return service, db, waiver


def _added_people(db):
    return [call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], BookingParticipant)]


def test_adult_guest_signs_only_their_own_waiver(monkeypatch):
    service, db, waiver = _service(monkeypatch, mode="per_guest")
    view = service.sign("t", _request(_adult("Jamie")), ip=None, user_agent=None)
    assert waiver.status == "signed" and view["guest_number"] == 2 and view["guest_total"] == 3
    assert [p.first_name for p in _added_people(db)] == ["Jamie"]


def test_guardian_signs_a_minors_waiver_without_joining_the_trip(monkeypatch):
    service, db, _ = _service(monkeypatch, mode="per_guest")
    child = {"first_name": "Kid", "last_name": "Smith", "date_of_birth": (date.today() - timedelta(days=365 * 8)).isoformat()}
    service.sign("t", _request(_adult("Parent"), [child]), ip=None, user_agent=None)
    people = _added_people(db)
    assert [(p.first_name, p.is_minor, p.guardian_name) for p in people] == [("Kid", True, "Parent Smith")]


@pytest.mark.parametrize("participants", [
    [_adult("Other")],  # another adult must sign their own
    [{"first_name": "A", "last_name": "B", "date_of_birth": "2018-01-01"},
     {"first_name": "C", "last_name": "D", "date_of_birth": "2019-01-01"}],  # one guest per waiver
])
def test_per_guest_waiver_covers_exactly_one_guest(monkeypatch, participants):
    service, _, waiver = _service(monkeypatch, mode="per_guest")
    with pytest.raises(ConflictError):
        service.sign("t", _request(_adult(), participants), ip=None, user_agent=None)
    assert waiver.status == "pending"


def test_party_waiver_still_needs_everyone_listed(monkeypatch):
    service, _, _ = _service(monkeypatch, mode="party", units=3)
    with pytest.raises(ConflictError, match="3 people"):
        service.sign("t", _request(_adult()), ip=None, user_agent=None)


def test_per_guest_links_list_every_unsigned_guest(monkeypatch):
    service = WaiverService(MagicMock())
    booking = SimpleNamespace(id=uuid.uuid4(), operator_id=uuid.uuid4(), booking_order_id=uuid.uuid4(), units=3, status="confirmed")
    waivers = [SimpleNamespace(guest_number=n, token=f"tok{n}", status="signed" if n == 2 else "pending") for n in (1, 2, 3)]
    monkeypatch.setattr(service, "configured", lambda operator_id: True)
    monkeypatch.setattr(service, "guest_waivers", lambda b: waivers)
    monkeypatch.setattr(module, "waiver_url", lambda token: f"https://p/waiver/{token}")
    assert service.links_for_bookings([booking])[booking.id] == "Guest 1: https://p/waiver/tok1\nGuest 3: https://p/waiver/tok3"


def test_order_request_accepts_the_staff_waiver_choice():
    base = {"items": [{"calendar_id": str(uuid.uuid4()), "start_at": "2027-01-04T15:00:00Z", "units": 2}],
            "customer": {"first_name": "Pat", "last_name": "Guest", "email": "pat@example.com"}}
    assert OrderCreateRequest(**base).waiver_mode is None
    assert OrderCreateRequest(**base, waiver_mode="per_guest").waiver_mode == "per_guest"
    with pytest.raises(ValueError):
        OrderCreateRequest(**base, waiver_mode="everyone")


def test_only_staff_paths_can_turn_on_per_guest_waivers():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "services" / "order_service.py").read_text(encoding="utf-8")
    assert 'if allow_payment_override and request.waiver_mode == "per_guest":' in source
