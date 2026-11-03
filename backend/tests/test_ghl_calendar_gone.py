"""A calendar deleted in HighLevel answers 400 "The calendar is deleted", not 404."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.ghl_calendar_service import GHLCalendarService, _remote_calendar_gone
from app.services.ghl_client import GHLAPIError

DELETED = GHLAPIError(
    "HighLevel request failed (400): {'message': 'The calendar is deleted', 'statusCode': 400}",
    status_code=400,
)


def test_deleted_and_missing_calendars_count_as_gone():
    assert _remote_calendar_gone(DELETED)
    assert _remote_calendar_gone(GHLAPIError("not found", status_code=404))
    assert not _remote_calendar_gone(GHLAPIError("HighLevel request failed (400): bad slot", status_code=400))
    assert not _remote_calendar_gone(GHLAPIError("rate limited", status_code=429))


def _service(calendar, mapping, calls):
    service = GHLCalendarService.__new__(GHLCalendarService)
    service.operator_id = calendar.operator_id
    service.settings = SimpleNamespace(ghl_calendar_sync_enabled=True)
    service.db = MagicMock()
    service.db.execute.return_value.one_or_none.return_value = (
        calendar, SimpleNamespace(ghl_location_id="loc-1"), None,
    )
    service.db.scalar.return_value = mapping

    def request(method, path, **kwargs):
        calls.append((method, path))
        if method == "PUT":
            raise DELETED
        if method == "GET":
            return {"calendars": []}
        return {"calendar": {"id": "ghl-new"}}

    service.client = SimpleNamespace(request=request)
    service._sync_schedule = lambda *args: None
    return service


def _calendar(*, deleted):
    return SimpleNamespace(
        id=uuid.uuid4(), operator_id=uuid.uuid4(), name="Sunset Cruise", is_active=not deleted,
        deleted_at=datetime.now(UTC) if deleted else None, duration_minutes=120,
        slot_interval_minutes=60, description=None, departure_location_id=None,
    )


def test_archived_calendar_already_deleted_in_highlevel_is_settled_not_retried():
    calls = []
    mapping = SimpleNamespace(ghl_calendar_id="ghl-old", desired_revision=8, applied_revision=7, status="pending", last_error=None)
    service = _service(_calendar(deleted=True), mapping, calls)
    service._calendar_description = lambda calendar: ""
    assert service.sync(uuid.uuid4()) is None
    assert (mapping.status, mapping.ghl_calendar_id, mapping.applied_revision) == ("deleted", None, 8)
    assert calls == [("PUT", "/calendars/ghl-old")]  # nothing recreated


def test_active_calendar_deleted_in_highlevel_is_recreated():
    calls = []
    mapping = SimpleNamespace(ghl_calendar_id="ghl-old", desired_revision=2, applied_revision=1, status="pending", last_error=None)
    service = _service(_calendar(deleted=False), mapping, calls)
    service._calendar_description = lambda calendar: ""
    service._find_remote_calendar = lambda operator, calendar: None
    assert service.sync(uuid.uuid4()) == "ghl-new"
    assert mapping.status == "synced"
    assert calls == [("PUT", "/calendars/ghl-old"), ("POST", "/calendars/")]
