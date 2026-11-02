import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.exceptions import ConflictError
from app.models.entities import (
    Booking,
    BookingNote,
    BookingOrder,
    Calendar,
    GHLCalendarMapping,
    OutboxJob,
    Payment,
)
from app.services import configuration_service
from app.services.configuration_service import ConfigurationService
from app.services.ghl_calendar_service import GHLCalendarService
from app.services.notification_service import NotificationService
from tests.test_waivers_integration import _booking, _calendar, _operator

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)


@pytest.fixture(autouse=True)
def no_inline_outbox(monkeypatch):
    # Removal drains the outbox inline; keep HighLevel calls out of these tests.
    class Idle:
        def __init__(self, *args, **kwargs):
            pass

        def process(self, *args, **kwargs):
            return {}

    monkeypatch.setattr(configuration_service, "OutboxService", Idle)


def _active_calendar(db):
    operator = _operator(db)
    calendar = _calendar(db, operator)
    calendar.is_active = True
    db.commit()
    return operator, calendar


def _jobs(db, calendar, job_type):
    return db.scalar(
        select(func.count()).select_from(OutboxJob).where(
            OutboxJob.job_type == job_type, OutboxJob.payload["calendar_id"].astext == str(calendar.id)
        )
    )


def _map_to_ghl(db, operator, calendar):
    db.add(GHLCalendarMapping(operator_id=operator.id, calendar_id=calendar.id, ghl_calendar_id="ghl-cal-1",
                              desired_revision=1, status="synced"))
    db.commit()


def test_calendar_with_history_is_archived_and_keeps_every_record(db):
    operator, calendar = _active_calendar(db)
    past = datetime.now(UTC) - timedelta(days=3)
    done = _booking(db, operator, calendar, start=past)
    cancelled = _booking(db, operator, calendar, start=datetime.now(UTC) + timedelta(days=2), status="cancelled")
    db.add(BookingNote(operator_id=operator.id, booking_id=done.id, body="Kept for history"))
    _map_to_ghl(db, operator, calendar)

    assert ConfigurationService(db, operator.id).delete_calendar(calendar.id) == "archived"

    db.expire_all()
    archived = db.get(Calendar, calendar.id)
    assert archived.deleted_at is not None and not archived.is_active and not archived.public_booking_enabled
    for booking in (done, cancelled):
        assert db.get(Booking, booking.id) is not None
        assert db.get(BookingOrder, booking.booking_order_id) is not None
        assert db.scalar(select(Payment.id).where(Payment.booking_order_id == booking.booking_order_id))
    assert db.scalar(select(BookingNote.body).where(BookingNote.booking_id == done.id)) == "Kept for history"
    assert calendar.id not in {c.id for c in ConfigurationService(db, operator.id).list_calendars()}
    # HighLevel keeps the calendar (and its past appointments), marked inactive.
    assert _jobs(db, calendar, "ghl_sync_calendar") == 1 and _jobs(db, calendar, "ghl_delete_calendar") == 0


def test_calendar_with_upcoming_bookings_cannot_be_removed(db):
    operator, calendar = _active_calendar(db)
    _booking(db, operator, calendar, start=datetime.now(UTC) + timedelta(days=1))

    with pytest.raises(ConflictError) as refused:
        ConfigurationService(db, operator.id).delete_calendar(calendar.id)
    assert "1 upcoming booking" in str(refused.value)
    db.expire_all()
    assert db.get(Calendar, calendar.id).deleted_at is None


def test_calendar_without_bookings_is_deleted_including_in_highlevel(db):
    operator, calendar = _active_calendar(db)
    _map_to_ghl(db, operator, calendar)

    assert ConfigurationService(db, operator.id).delete_calendar(calendar.id) == "deleted"
    assert _jobs(db, calendar, "ghl_delete_calendar") == 1


def test_highlevel_sync_never_creates_a_calendar_for_an_archived_one(db):
    operator, calendar = _active_calendar(db)
    calendar.deleted_at = datetime.now(UTC)
    db.commit()
    service = GHLCalendarService.__new__(GHLCalendarService)
    service.db, service.operator_id = db, operator.id
    service.settings = type("S", (), {"ghl_calendar_sync_enabled": True})()

    assert service.sync(calendar.id) is None
    assert db.scalar(select(GHLCalendarMapping.id).where(GHLCalendarMapping.calendar_id == calendar.id)) is None


def test_unstaffed_bookings_raise_no_notification(db):
    operator, calendar = _active_calendar(db)
    _booking(db, operator, calendar, start=datetime.now(UTC) + timedelta(days=1))

    items = NotificationService(db, operator.id).list().items
    assert all(item.type != "booking_staff" for item in items)


def test_category_with_upcoming_bookings_cannot_be_removed(db):
    from app.models.entities import CalendarCategory

    operator, calendar = _active_calendar(db)
    category = CalendarCategory(operator_id=operator.id, name="Cruises", slug="cruises")
    db.add(category)
    db.flush()
    calendar.calendar_category_id = category.id
    db.commit()
    booking = _booking(db, operator, calendar, start=datetime.now(UTC) + timedelta(days=1))

    with pytest.raises(ConflictError):
        ConfigurationService(db, operator.id).delete_category(category.id)
    db.expire_all()
    assert db.get(Calendar, calendar.id).deleted_at is None

    db.get(Booking, booking.id).status = "cancelled"
    db.commit()
    ConfigurationService(db, operator.id).delete_category(category.id)
    db.expire_all()
    assert db.get(Calendar, calendar.id).deleted_at is not None
    assert db.get(Booking, booking.id) is not None
