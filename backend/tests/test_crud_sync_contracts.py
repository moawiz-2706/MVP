from types import SimpleNamespace

import pytest

from app.core.exceptions import ConflictError
from app.services.booking_admin_service import BookingAdminService
from app.services.ghl_appointment_service import GHLAppointmentService
from app.services.ghl_auth_service import REQUIRED_SCOPES
from app.services.ghl_calendar_service import GHLCalendarService


def test_highlevel_calendar_and_appointment_scopes_are_required() -> None:
    assert {
        "calendars.readonly",
        "calendars.write",
        "calendars/events.readonly",
        "calendars/events.write",
    }.issubset(REQUIRED_SCOPES)


def test_highlevel_calendar_schedule_is_complete_week() -> None:
    rules = GHLCalendarService._schedule_rules()
    assert [rule["day"] for rule in rules] == [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
    assert all(rule["intervals"] == [{"from": "00:00", "to": "00:00"}] for rule in rules)


def test_remote_calendar_recovery_prefers_stable_passport_slug() -> None:
    service = GHLCalendarService.__new__(GHLCalendarService)

    class FakeClient:
        def request(self, method, path, *, version, params):
            assert (method, path, version) == ("GET", "/calendars/", "v3")
            assert params == {"locationId": "location-1"}
            return {
                "calendars": [
                    {"id": "remote-1", "name": "Sunset Cruise", "slug": "sunset-cruise"},
                    {"id": "remote-2", "name": "Sunset Cruise", "slug": "other-calendar"},
                ]
            }

    service.client = FakeClient()
    remote_id = service._find_remote_calendar(
        SimpleNamespace(ghl_location_id="location-1"),
        SimpleNamespace(name="Sunset Cruise", slug="sunset-cruise"),
    )
    assert remote_id == "remote-1"


def test_appointment_title_uses_contact_name_and_base_unit_price() -> None:
    booking = SimpleNamespace(base_price_minor=12500)
    order = SimpleNamespace(
        customer_first_name="Ada",
        customer_last_name="Lovelace",
        currency="usd",
    )
    assert (
        GHLAppointmentService._appointment_title(booking, order, ["Grace Hopper"])
        == "Ada Lovelace – USD 125.00 and Grace Hopper"
    )


def test_appointment_title_handles_unassigned_staff() -> None:
    booking = SimpleNamespace(base_price_minor=0)
    order = SimpleNamespace(
        customer_first_name="Ada",
        customer_last_name="Lovelace",
        currency="usd",
    )
    assert (
        GHLAppointmentService._appointment_title(booking, order)
        == "Ada Lovelace – USD 0.00 and Unassigned"
    )


def test_appointment_status_maps_passport_booking_states() -> None:
    states = {
        "pending_payment": "new",
        "confirmed": "confirmed",
        "cancelled": "cancelled",
        "completed": "completed",
        "no_show": "noshow",
    }
    for passport_status, ghl_status in states.items():
        assert (
            GHLAppointmentService._appointment_status(
                SimpleNamespace(status=passport_status)
            )
            == ghl_status
        )


def test_booking_update_rejects_terminal_booking() -> None:
    service = BookingAdminService.__new__(BookingAdminService)
    service.operator_id = SimpleNamespace()
    booking = SimpleNamespace(
        id="booking",
        operator_id=service.operator_id,
        booking_order_id="order",
        status="completed",
    )
    rows = iter([booking, SimpleNamespace(customer_total_minor=0, status="succeeded")])
    service.db = SimpleNamespace(
        scalar=lambda *_args, **_kwargs: next(rows),
    )
    with pytest.raises(ConflictError, match="Only pending or confirmed bookings"):
        service.update("booking", SimpleNamespace(start_at=None, units=None))


def test_worker_exposes_outbox_drain_for_calendar_and_booking_jobs(monkeypatch) -> None:
    import worker

    calls = []

    class FakeOutbox:
        def __init__(self, db, settings):
            calls.append((db, settings))

        def drain(self, *, budget_seconds):
            calls.append(budget_seconds)
            return {"claimed": 2, "completed": 2, "failed": 0}

    class FakeSession:
        def __enter__(self):
            return "db"

        def __exit__(self, *_args):
            return False

    class FakeFactory:
        def __call__(self):
            return FakeSession()

    monkeypatch.setattr(worker, "get_settings", lambda: "settings")
    monkeypatch.setattr(worker, "get_session_factory", lambda: FakeFactory())
    monkeypatch.setattr(worker, "OutboxService", FakeOutbox)

    assert worker.drain_outbox_once(budget_seconds=3.0) == {
        "claimed": 2,
        "completed": 2,
        "failed": 0,
    }
    assert calls == [("db", "settings"), 3.0]
