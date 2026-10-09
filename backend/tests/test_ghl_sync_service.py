import uuid

from app.models.entities import Booking, BookingOrder
from app.services import ghl_sync_service
from app.services.ghl_client import GHLAPIError
from app.services.ghl_sync_service import GHLSyncService


class FakeDB:
    def __init__(self):
        self.rows = []

    def add(self, value):
        self.rows.append(value)

    def commit(self):
        return None

    def refresh(self, _value):
        return None

    def execute(self, _statement):
        return None

    def get(self, _model, _key):
        return None

    def scalar(self, _statement):
        return None


def _bundle():
    operator_id = uuid.uuid4()
    order = BookingOrder(id=uuid.uuid4(), operator_id=operator_id, ghl_contact_id=None)
    booking = Booking(
        id=uuid.uuid4(),
        operator_id=operator_id,
        booking_order_id=order.id,
        start_at=None,
    )
    return operator_id, order, [booking]


def test_sync_succeeds_on_second_attempt(monkeypatch):
    operator_id, order, bookings = _bundle()
    db = FakeDB()
    sleeps = []
    contact_calls = 0

    class Contact:
        def __init__(self, _db, _operator_id):
            pass

        def sync(self, _order_id):
            nonlocal contact_calls
            contact_calls += 1
            if contact_calls == 1:
                raise GHLAPIError("temporary", status_code=503)
            return "contact-1"

    class Appointment:
        def __init__(self, _db, _operator_id):
            pass

        def sync(self, _booking_id):
            return "appointment-1"

    monkeypatch.setattr(ghl_sync_service, "GHLContactService", Contact)
    monkeypatch.setattr(ghl_sync_service, "GHLAppointmentService", Appointment)
    service = GHLSyncService(db, operator_id, sleep=sleeps.append)
    monkeypatch.setattr(service, "_order_bundle", lambda _order_id: (order, bookings))

    result = service.sync_order(order.id)

    assert result.status == "succeeded"
    assert result.attempts == 2
    assert result.contact_id == "contact-1"
    assert result.appointment_ids == ("appointment-1",)
    assert sleeps == [0.5]
    assert contact_calls == 2


def test_sync_records_three_failures_without_raising(monkeypatch):
    operator_id, order, bookings = _bundle()
    db = FakeDB()
    sleeps = []

    class Contact:
        def __init__(self, _db, _operator_id):
            pass

        def sync(self, _order_id):
            raise GHLAPIError("HighLevel unavailable", status_code=503)

    monkeypatch.setattr(ghl_sync_service, "GHLContactService", Contact)
    service = GHLSyncService(db, operator_id, sleep=sleeps.append)
    monkeypatch.setattr(service, "_order_bundle", lambda _order_id: (order, bookings))

    result = service.sync_order(order.id)

    assert result.status == "failed"
    assert result.attempts == 3
    assert result.error_code == "ghl_provider_unavailable"
    assert result.error == "HighLevel unavailable"
    assert sleeps == [0.5, 1.0]
    assert len([row for row in db.rows if row.__class__.__name__ == "GHLSyncAttempt"]) == 3


def test_error_details_preserve_provider_status():
    code, status, message = GHLSyncService._error_details(
        GHLAPIError("rate limited", status_code=429)
    )
    assert code == "ghl_rate_limited"
    assert status == 429
    assert message == "rate limited"
