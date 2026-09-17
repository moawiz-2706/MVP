from types import SimpleNamespace

import pytest

from app.core.exceptions import ConflictError
from app.services.booking_admin_service import BookingAdminService
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
