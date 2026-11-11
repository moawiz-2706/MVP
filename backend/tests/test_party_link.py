import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.api.v1 import bookings, public, staff_booking
from app.models.entities import PublicAccessCredential
from app.services import party_service
from app.services.party_service import PURPOSE, PartyService


def test_party_purpose_is_allowed_by_the_model_constraint():
    texts = [str(getattr(c, "sqltext", "")) for c in PublicAccessCredential.__table__.constraints]
    assert any("'staff_booking'" in text and "'party_details'" in text for text in texts)


def test_routes_are_registered():
    assert any(r.path == "/public/party/{token}" for r in public.router.routes)
    assert any(r.path == "/staff-booking/{token}/orders/{public_reference}/party-link" for r in staff_booking.router.routes)
    # Passport/PWA "New booking" shows the same QR code after booking.
    assert any(r.path == "/bookings/orders/{public_reference}/party-link" for r in bookings.router.routes)


class _Scalars(list):
    pass


class _DB:
    def __init__(self, order, operator, bookings):
        self.order, self.operator, self.bookings = order, operator, bookings

    def get(self, model, _id):
        return self.order if model.__name__ == "BookingOrder" else self.operator

    def scalars(self, _query):
        return _Scalars(self.bookings)


def test_view_lists_one_link_per_guest_and_hides_unpaid_waivers(monkeypatch):
    order = SimpleNamespace(id=uuid.uuid4(), operator_id=uuid.uuid4(), public_reference="RM-1", customer_first_name="Pat")
    operator = SimpleNamespace(id=order.operator_id, name="Oasis", time_zone="America/New_York")
    paid = SimpleNamespace(id=uuid.uuid4(), status="confirmed", calendar_name_snapshot="Kayak", start_at=datetime(2026, 12, 1, tzinfo=UTC), units=2)
    unpaid = SimpleNamespace(id=uuid.uuid4(), status="pending_payment", calendar_name_snapshot="Cruise", start_at=datetime(2026, 12, 2, tzinfo=UTC), units=1)
    db = _DB(order, operator, [paid, unpaid])

    monkeypatch.setattr(
        party_service.PublicAccessService, "verify",
        lambda self, token, **kw: SimpleNamespace(order_id=order.id) if kw["purpose"] == PURPOSE else None,
    )

    class Waivers:
        def __init__(self, _db): pass
        def configured(self, _id): return True
        def per_guest(self, _booking): return True
        def guest_waivers(self, booking):
            return [
                SimpleNamespace(guest_number=1, token="t1", status="signed", details={"signer": {"first_name": "Amy", "last_name": "Lee"}}),
                SimpleNamespace(guest_number=2, token="t2", status="pending", details=None),
            ]

    monkeypatch.setattr(party_service, "WaiverService", Waivers)
    view = PartyService(db).view("tok")
    first, second = view["items"]
    assert [g["label"] for g in first["guests"]] == ["Guest 1", "Guest 2"]
    assert first["guests"][0]["signed_by"] == "Amy Lee" and first["guests"][1]["signed"] is False
    assert second["waivers_open"] is False and second["guests"] == []
