from types import SimpleNamespace

import pytest

from app.core.exceptions import ConflictError
from app.services.booking_admin_service import BookingAdminService
from app.services.ghl_auth_service import REQUIRED_SCOPES
from app.services.ghl_appointment_service import GHLAppointmentService
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


def test_ghl_appointment_description_contains_passport_details() -> None:
    service = GHLAppointmentService.__new__(GHLAppointmentService)
    booking = SimpleNamespace(
        id="booking-1",
        units=2,
        departure_location_name_snapshot="Marina",
        departure_location_address_snapshot="1 Harbor Way",
    )
    order = SimpleNamespace(
        public_reference="PASSPORT-123",
        customer_first_name="Ada",
        customer_last_name="Lovelace",
        customer_email="ada@example.com",
        customer_phone="+15551234567",
    )
    calendar = SimpleNamespace(name="Kayak Rental")
    description = service._description(
        booking,
        order,
        calendar,
        [("Single Kayak", 2)],
        [("Grace Hopper", "Guide")],
    )
    assert "PASSPORT-123" in description
    assert "Ada Lovelace" in description
    assert "Single Kayak: 2" in description
    assert "Grace Hopper (Guide)" in description
