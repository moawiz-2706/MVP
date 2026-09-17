"""Focused Captain readiness and reassignment contract tests."""
from datetime import date, time
from types import SimpleNamespace

import pytest

from app.schemas.booking import BookingNotificationsResponse
from app.schemas.staff import StaffAssignmentUpdate
from app.services.staffing_service import is_captain


def test_captain_role_is_trimmed_and_case_insensitive() -> None:
    assert is_captain(" Captain ")
    assert is_captain("CAPTAIN")
    assert not is_captain("Deckhand")
    assert not is_captain(None)


def test_assignment_patch_preserves_omitted_role() -> None:
    update = StaffAssignmentUpdate.model_validate({"staff_id": "00000000-0000-0000-0000-000000000001"})
    assert "role" not in update.model_fields_set
    assert update.staff_id is not None


def test_assignment_patch_normalizes_explicit_role() -> None:
    update = StaffAssignmentUpdate.model_validate({"role": "  Captain  "})
    assert update.role == "Captain"
    assert "role" in update.model_fields_set


def test_notification_response_contract_accepts_bounded_payload() -> None:
    item = {
        "booking_id": "00000000-0000-0000-0000-000000000001",
        "calendar_id": "00000000-0000-0000-0000-000000000002",
        "calendar_name": "Cruise",
        "customer_name": "Ada Lovelace",
        "start_at": "2027-06-15T13:00:00Z",
        "end_at": "2027-06-15T16:00:00Z",
        "units": 2,
        "status": "confirmed",
        "created_at": "2027-06-01T12:00:00Z",
        "assignment_status": "pending",
        "captain_name": None,
        "reason": "Exactly one active Captain must cover the entire booking",
    }
    parsed = BookingNotificationsResponse.model_validate({"items": [item], "pending_count": 1})
    assert parsed.items[0].assignment_status == "pending"
    assert parsed.pending_count == 1


@pytest.mark.skipif(not __import__("os").getenv("TEST_DATABASE_URL"), reason="Postgres integration test")
def test_db_workflow_placeholder_is_gated() -> None:
    # Full row-lock/concurrency coverage remains in test_staff_integration.py.
    assert date(2027, 6, 15).weekday() == 1
