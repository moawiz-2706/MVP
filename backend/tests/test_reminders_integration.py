"""DB-backed tests for daily reminders, staff Contacts, and staff emails.

HighLevel is replaced by the recording fake in conftest so the exact calls Passport makes
(contact upsert, tag add, message send) can be asserted. Gated on
TEST_DATABASE_URL.
"""

import os
import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models.entities import (
    Booking,
    BookingOrder,
    Calendar,
    GHLInstallation,
    Operator,
    OperatorSettings,
    OutboxJob,
    Staff,
    StaffHour,
)
from app.schemas.staff import StaffAssignmentCreate, StaffCreate, StaffHourWrite
from app.services.outbox_service import OutboxService
from app.services.reminder_service import ReminderService
from app.services.staff_service import StaffService
from app.utils.timezone import local_datetime, require_timezone

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)

TZ = "America/New_York"
FIXED_NOW = datetime(2026, 9, 14, 11, 30, tzinfo=UTC)  # Mon 07:30 EDT


def _messages(calls):
    return [body for method, path, body in calls if path == "/conversations/messages"]


def _operator(db, *, customer_emails=True) -> Operator:
    op = Operator(
        ghl_location_id=f"loc-{uuid.uuid4()}",
        name="Punta Gorda Rentals",
        slug=f"op-{uuid.uuid4().hex[:8]}",
        time_zone=TZ,
    )
    db.add(op)
    db.flush()
    db.add(
        GHLInstallation(
            operator_id=op.id,
            location_id=op.ghl_location_id,
            access_token_encrypted="x",
            refresh_token_encrypted="x",
            access_token_expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    db.add(OperatorSettings(operator_id=op.id, confirmation_email_enabled=customer_emails))
    db.flush()
    return op


def _calendar(db, op) -> Calendar:
    cal = Calendar(operator_id=op.id, name="Sunset Cruise", slug=f"c-{uuid.uuid4().hex[:6]}", duration_minutes=180)
    db.add(cal)
    db.flush()
    return cal


def _booking(db, op, cal, start, *, status="confirmed", first="Ada") -> Booking:
    order = BookingOrder(
        operator_id=op.id,
        public_reference=f"RM-{uuid.uuid4().hex[:12]}",
        customer_first_name=first,
        customer_last_name="Tester",
        customer_email=f"{first.lower()}@example.com",
        subtotal_minor=0,
        platform_fee_and_taxes_minor=0,
        customer_total_minor=0,
        operator_transfer_minor=0,
        platform_gross_retained_minor=0,
        status=status,
    )
    db.add(order)
    db.flush()
    booking = Booking(
        operator_id=op.id,
        booking_order_id=order.id,
        calendar_id=cal.id,
        start_at=start,
        end_at=start + timedelta(minutes=cal.duration_minutes),
        units=2,
        base_price_minor=0,
        status=status,
        hold_expires_at=start if status == "pending_payment" else None,
        calendar_name_snapshot=cal.name,
    )
    db.add(booking)
    db.flush()
    return booking


def _local(day_offset: int, hour: int, *, base: datetime) -> datetime:
    today = base.astimezone(require_timezone(TZ)).date()
    return local_datetime(today + timedelta(days=day_offset), time(hour), TZ)


def _jobs(db, job_type):
    return list(db.scalars(select(OutboxJob).where(OutboxJob.job_type == job_type)))


# --- Scheduling ----------------------------------------------------------------


def test_enqueue_picks_confirmed_bookings_today_and_tomorrow_only(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op)
    due_tomorrow = _booking(db, op, cal, _local(1, 9, base=FIXED_NOW))
    due_today = _booking(db, op, cal, _local(0, 13, base=FIXED_NOW))
    _booking(db, op, cal, _local(0, 6, base=FIXED_NOW))  # already started at 07:30
    _booking(db, op, cal, _local(1, 10, base=FIXED_NOW), status="cancelled")
    _booking(db, op, cal, _local(1, 11, base=FIXED_NOW), status="pending_payment")
    _booking(db, op, cal, _local(3, 9, base=FIXED_NOW))  # too far ahead
    db.commit()

    counts = ReminderService(db).enqueue(now=FIXED_NOW)
    assert counts["customer_reminders_queued"] == 2
    queued = {(job.payload["booking_id"], job.payload["kind"]) for job in _jobs(db, "ghl_booking_reminder")}
    assert queued == {(str(due_tomorrow.id), "day_before"), (str(due_today.id), "same_day")}


def test_enqueue_is_idempotent_across_repeat_runs(db) -> None:
    op = _operator(db)
    _booking(db, op, _calendar(db, op), _local(1, 9, base=FIXED_NOW))
    db.commit()
    assert ReminderService(db).enqueue(now=FIXED_NOW)["customer_reminders_queued"] == 1
    assert ReminderService(db).enqueue(now=FIXED_NOW)["customer_reminders_queued"] == 0
    assert len(_jobs(db, "ghl_booking_reminder")) == 1


def test_customer_reminders_respect_the_operator_email_switch(db) -> None:
    op = _operator(db, customer_emails=False)
    _booking(db, op, _calendar(db, op), _local(1, 9, base=FIXED_NOW))
    db.commit()
    assert ReminderService(db).enqueue(now=FIXED_NOW)["customer_reminders_queued"] == 0


def test_staff_reminders_only_for_active_staff_with_email(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op)
    db.commit()
    service = StaffService(db, op.id)
    all_week = [StaffHourWrite(day_of_week=d, start_time=time(0), end_time=time(23, 59)) for d in range(7)]
    with_email = service.create_staff(StaffCreate(name="Sam Captain", email="sam@example.com", hours=all_week))
    no_email = service.create_staff(StaffCreate(name="Nia NoEmail", hours=all_week))
    start = _local(1, 9, base=datetime.now(UTC))
    for member in (with_email, no_email):
        service.assign(StaffAssignmentCreate(staff_id=member["id"], calendar_id=cal.id, start_at=start))
    counts = ReminderService(db).enqueue()
    assert counts["staff_reminders_queued"] == 1
    assert [job.payload["kind"] for job in _jobs(db, "ghl_staff_reminder")] == ["day_before"]


# --- Sending through HighLevel -------------------------------------------------


def test_customer_reminder_creates_tagged_contact_and_sends(db, ghl) -> None:
    op = _operator(db)
    booking = _booking(db, op, _calendar(db, op), _local(1, 10, base=datetime.now(UTC)))
    db.commit()
    ReminderService(db).enqueue()
    OutboxService(db, Settings()).process()

    created = [body for method, path, body in ghl if method == "POST" and path == "/contacts/"]
    assert created and created[0]["email"] == "ada@example.com" and "tags" not in created[0]
    tag_calls = [(path, body) for method, path, body in ghl if path.endswith("/tags")]
    assert tag_calls and tag_calls[0][1] == {"tags": ["passport-customer"]}
    (message,) = _messages(ghl)
    assert message["subject"] == "Reminder: your booking is tomorrow - Punta Gorda Rentals"
    assert message["contactId"] == tag_calls[0][0].split("/")[2]
    db.refresh(booking)
    order = db.get(BookingOrder, booking.booking_order_id)
    assert order.ghl_contact_id == message["contactId"]


def test_cancelled_after_queueing_sends_nothing(db, ghl) -> None:
    op = _operator(db)
    booking = _booking(db, op, _calendar(db, op), _local(1, 10, base=datetime.now(UTC)))
    db.commit()
    ReminderService(db).enqueue()
    booking.status = "cancelled"
    db.commit()
    result = OutboxService(db, Settings()).process()
    assert result["completed"] == 1 and _messages(ghl) == []


def test_reminder_no_longer_due_is_skipped_at_send_time(db, ghl) -> None:
    # A day-before job whose booking is not tomorrow (e.g. rescheduled) must not
    # send. The "retried the next morning" case is covered in test_reminders.py.
    op = _operator(db)
    booking = _booking(db, op, _calendar(db, op), _local(3, 10, base=datetime.now(UTC)))
    db.add(
        OutboxJob(
            operator_id=op.id,
            booking_order_id=booking.booking_order_id,
            job_type="ghl_booking_reminder",
            idempotency_key=f"booking:{booking.id}:reminder:day_before",
            payload={"booking_id": str(booking.id), "kind": "day_before"},
            status="pending",
        )
    )
    db.commit()
    assert OutboxService(db, Settings()).process()["completed"] == 1
    assert _messages(ghl) == []


def test_staff_contact_is_created_with_staff_tag(db, ghl) -> None:
    op = _operator(db)
    db.commit()
    staff = StaffService(db, op.id).create_staff(StaffCreate(name="Sam Captain", email="sam@example.com"))
    OutboxService(db, Settings()).process()
    created = [body for method, path, body in ghl if method == "POST" and path == "/contacts/"]
    assert created[0]["firstName"] == "Sam" and created[0]["lastName"] == "Captain"
    assert created[0]["locationId"] == op.ghl_location_id
    assert [body for _, path, body in ghl if path.endswith("/tags")] == [{"tags": ["passport-staff"]}]
    assert db.get(Staff, staff["id"]).ghl_contact_id


def test_staff_without_email_gets_no_contact_or_email(db, ghl) -> None:
    op = _operator(db)
    cal = _calendar(db, op)
    db.commit()
    service = StaffService(db, op.id)
    staff = service.create_staff(
        StaffCreate(name="Nia", hours=[StaffHourWrite(day_of_week=d, start_time=time(0), end_time=time(23, 59)) for d in range(7)])
    )
    service.assign(StaffAssignmentCreate(staff_id=staff["id"], calendar_id=cal.id, start_at=_local(1, 9, base=datetime.now(UTC))))
    assert OutboxService(db, Settings()).process()["claimed"] == 0
    assert ghl == []


def test_assignment_sends_immediate_email_with_role_and_guests(db, ghl) -> None:
    op = _operator(db)
    cal = _calendar(db, op)
    start = _local(1, 9, base=datetime.now(UTC))
    _booking(db, op, cal, start)  # 2 units booked on that slot
    db.commit()
    service = StaffService(db, op.id)
    staff = service.create_staff(
        StaffCreate(
            name="Sam Captain",
            email="sam@example.com",
            hours=[StaffHourWrite(day_of_week=d, start_time=time(0), end_time=time(23, 59)) for d in range(7)],
        )
    )
    service.assign(StaffAssignmentCreate(staff_id=staff["id"], calendar_id=cal.id, start_at=start, role="Captain"))
    OutboxService(db, Settings()).process()
    (message,) = _messages(ghl)
    assert message["subject"].startswith("You're scheduled: Sunset Cruise on ")
    assert "as Captain" in message["message"] and "Guests booked so far: 2" in message["message"]
    assert message["contactId"] == db.get(Staff, staff["id"]).ghl_contact_id


def test_staff_hours_rows_are_unaffected_by_contact_fields(db) -> None:
    # Guard: the new ghl_contact_id column must not disturb staff CRUD round-trips.
    op = _operator(db)
    db.commit()
    created = StaffService(db, op.id).create_staff(
        StaffCreate(name="Ana", hours=[StaffHourWrite(day_of_week=1, start_time=time(8), end_time=time(12))])
    )
    assert db.scalar(select(StaffHour.staff_id).where(StaffHour.staff_id == created["id"])) is not None
