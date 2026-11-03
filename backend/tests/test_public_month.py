"""The month view is one batch but must agree with the day view (TEST_DATABASE_URL)."""

import os
import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest

from app.models.entities import Calendar, CalendarHour, CalendarPushedSlot, Operator
from app.services.availability_service import AvailabilityService

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)


@pytest.mark.parametrize("mode", ["pushed", "day_wise"])
def test_month_matches_day_by_day(db, mode):
    operator = Operator(ghl_location_id=f"loc-{uuid.uuid4().hex}", name="Op", slug=f"op-{uuid.uuid4().hex[:8]}",
                        time_zone="America/New_York", public_booking_enabled=True)
    db.add(operator)
    db.flush()
    calendar = Calendar(operator_id=operator.id, name="Tour", slug=f"t-{uuid.uuid4().hex[:8]}", duration_minutes=60,
                        slot_interval_minutes=60, base_price_minor=5000, public_booking_enabled=True,
                        availability_mode=mode)
    db.add(calendar)
    db.flush()
    next_month = (datetime.now(UTC).date().replace(day=1) + timedelta(days=40)).replace(day=1)
    if mode == "pushed":
        for offset in (2, 3, 9):
            day = next_month + timedelta(days=offset)
            db.add(CalendarPushedSlot(calendar_id=calendar.id, start_at=datetime.combine(day, time(19), tzinfo=UTC)))
    else:
        db.add_all([CalendarHour(calendar_id=calendar.id, day_of_week=d, start_time=time(9), end_time=time(11)) for d in (0, 2)])
    db.commit()

    service = AvailabilityService(db)
    month = service.public_month(operator.slug, calendar.slug, next_month.year, next_month.month)
    for entry in month["days"]:
        day_slots = service.public_day(operator.slug, calendar.slug, entry["date"]).slots
        expected = "available" if any(s.available for s in day_slots) else ("sold_out" if day_slots else "none")
        assert entry["status"] == expected, entry["date"]
    assert any(entry["status"] == "available" for entry in month["days"])
