"""Pure-logic tests for reminder timing and email content."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.models.entities import Booking, BookingOrder, DepartureLocation, Operator
from app.services.ghl_email_service import booking_reminder_content, staff_content
from app.services.reminder_service import reminder_still_due, reminder_windows

TZ = "America/New_York"
NY = ZoneInfo(TZ)
# Monday 2026-09-14 at 07:30 EDT, when the daily cron fires.
NOW = datetime(2026, 9, 14, 11, 30, tzinfo=UTC)


def test_windows_cover_rest_of_today_and_all_of_tomorrow() -> None:
    windows = reminder_windows(NOW, TZ)
    assert windows["same_day"] == (NOW, datetime(2026, 9, 15, 0, tzinfo=NY))
    assert windows["day_before"] == (datetime(2026, 9, 15, 0, tzinfo=NY), datetime(2026, 9, 16, 0, tzinfo=NY))


def test_windows_follow_local_days_across_dst() -> None:
    # US clocks fall back on Sunday 2026-11-01, so that local day is 25 hours long.
    windows = reminder_windows(datetime(2026, 10, 31, 11, 30, tzinfo=UTC), TZ)
    start, end = windows["day_before"]
    assert end - start == timedelta(hours=25)


def test_day_before_reminder_is_not_sent_on_the_day() -> None:
    booking = datetime(2026, 9, 15, 9, 0, tzinfo=NY)
    assert reminder_still_due("day_before", booking, NOW, TZ)
    assert not reminder_still_due("same_day", booking, NOW, TZ)
    next_morning = NOW + timedelta(days=1)  # a failed job retried by the next cron
    assert not reminder_still_due("day_before", booking, next_morning, TZ)
    assert reminder_still_due("same_day", booking, next_morning, TZ)


def test_same_day_reminder_skips_bookings_already_under_way() -> None:
    started = datetime(2026, 9, 14, 7, 0, tzinfo=NY)  # before the 07:30 run
    assert not reminder_still_due("same_day", started, NOW, TZ)


def _operator() -> Operator:
    return Operator(name="Punta Gorda Rentals", slug="pg", time_zone=TZ, ghl_location_id="loc")


def test_customer_reminder_content_names_the_day_and_details() -> None:
    order = BookingOrder(customer_first_name="Ada", public_reference="RM-ABC")
    booking = Booking(
        calendar_name_snapshot="Sunset Cruise",
        start_at=datetime(2026, 9, 15, 13, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 15, 16, 0, tzinfo=UTC),
        units=2,
        departure_location_name_snapshot="Fishermen's Village",
    )
    subject, plain, markup = booking_reminder_content(order, _operator(), booking, "day_before")
    assert subject == "Reminder: your booking is tomorrow - Punta Gorda Rentals"
    assert "Time: 9:00 AM - 12:00 PM EDT" in plain and "Quantity: 2" in plain and "RM-ABC" in plain
    assert "Fishermen&#x27;s Village" in markup


def test_staff_assigned_content_has_role_location_and_guests() -> None:
    location = DepartureLocation(name="Dock 4", address="1200 W Retta Esplanade")
    subject, plain, markup = staff_content(
        "assigned",
        staff_name="Sam Captain",
        role="Captain",
        calendar_name="<Sunset & Co>",
        start=datetime(2026, 9, 15, 9, 0, tzinfo=NY),
        end=datetime(2026, 9, 15, 12, 0, tzinfo=NY),
        location=location,
        guests=6,
        operator_name="Punta Gorda Rentals",
    )
    assert subject == "You're scheduled: <Sunset & Co> on Sep 15 - Punta Gorda Rentals"
    assert plain.startswith("Hi Sam,") and "as Captain" in plain
    assert "Role: Captain" in plain and "Location: Dock 4" in plain and "Guests booked so far: 6" in plain
    assert "&lt;Sunset &amp; Co&gt;" in markup and "<Sunset" not in markup


def test_staff_reminder_subject_says_when() -> None:
    subject, _, _ = staff_content(
        "same_day",
        staff_name="Ana",
        role=None,
        calendar_name="Kayak Tour",
        start=datetime(2026, 9, 15, 13, 0, tzinfo=NY),
        end=datetime(2026, 9, 15, 14, 0, tzinfo=NY),
        location=None,
        guests=0,
        operator_name="PG",
    )
    assert subject == "Reminder: Kayak Tour today at 1:00 PM - PG"
