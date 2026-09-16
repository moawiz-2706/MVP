"""DB-backed tests for waivers, booking notes, and the staff removal email.

Gated on TEST_DATABASE_URL. The signed-waiver lock trigger is attached to the
test schema by the model's DDL listener, mirroring migration 007.
"""

import base64
import os
import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from app.api.v1.orders import order_status
from app.core.config import Settings
from app.core.exceptions import ConflictError, DomainError
from app.models.entities import (
    AppUser,
    Booking,
    BookingOrder,
    BookingWaiver,
    Calendar,
    GHLInstallation,
    Operator,
    OperatorSettings,
    OutboxJob,
    Payment,
)
from app.schemas.staff import StaffAssignmentCreate, StaffCreate, StaffHourWrite
from app.schemas.waiver import WaiverSignRequest
from app.services.booking_admin_service import BookingAdminService
from app.services.outbox_service import OutboxService
from app.services.reminder_service import ReminderService
from app.services.staff_service import StaffService
from app.services.waiver_service import WaiverService
from app.utils.timezone import local_datetime, require_timezone

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)

TZ = "America/New_York"
TEXT = "##ACKNOWLEDGEMENT OF RISKS##\n\nI accept the risks of this charter."
PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode()
ALL_WEEK = [StaffHourWrite(day_of_week=d, start_time=time(0), end_time=time(23, 59)) for d in range(7)]


def _tomorrow(hour: int) -> datetime:
    today = datetime.now(UTC).astimezone(require_timezone(TZ)).date()
    return local_datetime(today + timedelta(days=1), time(hour), TZ)


def _operator(db, *, waiver_text: str | None = TEXT) -> Operator:
    op = Operator(
        ghl_location_id=f"loc-{uuid.uuid4()}",
        name="Punta Gorda Adventures",
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
    db.add(
        OperatorSettings(
            operator_id=op.id,
            waiver_title="PGA Waiver",
            waiver_text=waiver_text,
            waiver_opt_in_label="I'm adventurous",
        )
    )
    db.flush()
    return op


def _calendar(db, op) -> Calendar:
    cal = Calendar(operator_id=op.id, name="Sunset Cruise", slug=f"c-{uuid.uuid4().hex[:6]}", duration_minutes=120)
    db.add(cal)
    db.flush()
    return cal


def _booking(db, op, cal, *, units: int = 3, status: str = "confirmed", start: datetime | None = None) -> Booking:
    start = start or _tomorrow(18)
    order = BookingOrder(
        operator_id=op.id,
        public_reference=f"RM-{uuid.uuid4().hex[:12]}",
        customer_first_name="Calvin",
        customer_last_name="Schofield",
        customer_email="calvin@example.com",
        subtotal_minor=0,
        platform_fee_and_taxes_minor=0,
        customer_total_minor=0,
        operator_transfer_minor=0,
        platform_gross_retained_minor=0,
        status=status,
    )
    db.add(order)
    db.flush()
    db.add(
        Payment(
            operator_id=op.id,
            booking_order_id=order.id,
            currency="usd",
            subtotal_minor=0,
            platform_fee_and_taxes_minor=0,
            customer_total_minor=0,
            operator_transfer_minor=0,
            platform_gross_retained_minor=0,
            status="succeeded",
        )
    )
    booking = Booking(
        operator_id=op.id,
        booking_order_id=order.id,
        calendar_id=cal.id,
        start_at=start,
        end_at=start + timedelta(minutes=cal.duration_minutes),
        units=units,
        base_price_minor=0,
        status=status,
        calendar_name_snapshot=cal.name,
    )
    db.add(booking)
    db.flush()
    return booking


def _sign_request(others: list[tuple[str, date]], *, signer_dob: date = date(1991, 7, 16)) -> WaiverSignRequest:
    return WaiverSignRequest(
        signer={
            "first_name": "Calvin",
            "last_name": "Schofield",
            "email": "calvin@example.com",
            "phone": "+19415550100",
            "date_of_birth": signer_dob,
        },
        address={"street": "4824 Fairway Dr S", "city": "Punta Gorda", "state": "FL", "postal_code": "33982", "country": "USA"},
        participants=[{"first_name": name, "last_name": "Hart", "date_of_birth": dob} for name, dob in others],
        opt_in=True,
        agreed=True,
        signature_png=PNG,
    )


def test_ensure_creates_one_waiver_per_booking(db) -> None:
    op = _operator(db)
    booking = _booking(db, op, _calendar(db, op))
    db.commit()
    first = WaiverService(db).ensure(booking)
    second = WaiverService(db).ensure(booking)
    assert first.id == second.id and len(first.token) >= 32
    assert len(list(db.scalars(select(BookingWaiver)))) == 1


def test_signing_records_everyone_snapshots_and_locks(db) -> None:
    op = _operator(db)
    booking = _booking(db, op, _calendar(db, op), units=3)
    db.commit()
    service = WaiverService(db)
    token = service.ensure(booking).token

    view = service.sign(
        token,
        _sign_request([("Jordan", date(1990, 1, 1)), ("Azaria", date(2015, 2, 10))]),
        ip="203.0.113.7",
        user_agent="pytest",
    )
    assert view["status"] == "signed" and view["title"] == "PGA Waiver"
    assert [p["minor"] for p in view["details"]["participants"]] == [False, True]
    assert view["details"]["opt_in"] is True
    waiver = service.get(booking.id)
    assert waiver.signer_ip == "203.0.113.7" and waiver.signature_png == PNG

    # Later edits to the operator's text never change what was signed.
    db.get(OperatorSettings, op.id).waiver_text = "Completely different text"
    db.commit()
    assert service.public_view(token)["waiver_text"] == TEXT

    with pytest.raises(ConflictError, match="already been signed"):
        service.sign(token, _sign_request([("A", date(1990, 1, 1)), ("B", date(1990, 1, 1))]), ip=None, user_agent=None)

    # The database itself refuses to change or delete a signed waiver.
    with pytest.raises(DBAPIError):
        db.execute(update(BookingWaiver).where(BookingWaiver.id == waiver.id).values(signer_ip="tampered"))
    db.rollback()
    with pytest.raises(DBAPIError):
        db.execute(delete(BookingWaiver).where(BookingWaiver.id == waiver.id))
    db.rollback()


def test_head_count_must_match_booking_quantity(db) -> None:
    op = _operator(db)
    booking = _booking(db, op, _calendar(db, op), units=3)
    db.commit()
    token = WaiverService(db).ensure(booking).token
    with pytest.raises(ConflictError, match="for 3 people"):
        WaiverService(db).sign(token, _sign_request([("Jordan", date(1990, 1, 1))]), ip=None, user_agent=None)


def test_person_signing_must_be_an_adult(db) -> None:
    op = _operator(db)
    booking = _booking(db, op, _calendar(db, op), units=1)
    db.commit()
    token = WaiverService(db).ensure(booking).token
    with pytest.raises(ConflictError, match="18 or older"):
        WaiverService(db).sign(token, _sign_request([], signer_dob=date(2012, 1, 1)), ip=None, user_agent=None)


def test_waiver_unavailable_when_not_set_up_or_booking_cancelled(db) -> None:
    op_without = _operator(db, waiver_text=None)
    no_text = _booking(db, op_without, _calendar(db, op_without), units=1)
    op = _operator(db)
    cancelled = _booking(db, op, _calendar(db, op), units=1, status="cancelled")
    db.commit()
    service = WaiverService(db)
    for booking in (no_text, cancelled):
        token = service.ensure(booking).token
        assert service.public_view(token)["status"] == "unavailable"
        with pytest.raises(ConflictError):
            service.sign(token, _sign_request([]), ip=None, user_agent=None)
    assert service.summary(no_text)["status"] == "not_set_up"
    assert service.summary(cancelled)["status"] == "not_applicable"


def test_booking_detail_shows_waiver_and_notes(db) -> None:
    op = _operator(db)
    booking = _booking(db, op, _calendar(db, op), units=1)
    author = AppUser(ghl_user_id=f"u-{uuid.uuid4()}", name="Avery Admin")
    db.add(author)
    db.commit()
    service = BookingAdminService(db, op.id)

    detail = service.detail(booking.id)
    assert detail["waiver"]["status"] == "pending" and "/waiver/" in detail["waiver"]["url"]

    note = service.add_note(booking.id, "Bring a cooler", author.id)
    notes = service.detail(booking.id)["notes"]
    assert [(n["body"], n["author_name"]) for n in notes] == [("Bring a cooler", "Avery Admin")]

    with pytest.raises(DomainError, match="your own notes"):
        service.delete_note(booking.id, note["id"], user_id=uuid.uuid4(), is_admin=False)
    service.delete_note(booking.id, note["id"], user_id=author.id, is_admin=False)
    assert service.detail(booking.id)["notes"] == []

    WaiverService(db).sign(WaiverService(db).get(booking.id).token, _sign_request([]), ip=None, user_agent=None)
    assert service.detail(booking.id)["waiver"]["status"] == "signed"


def test_confirmation_page_lists_waiver_links(db) -> None:
    op = _operator(db)
    booking = _booking(db, op, _calendar(db, op), units=1)
    db.commit()
    reference = db.get(BookingOrder, booking.booking_order_id).public_reference
    item = order_status(reference, db).items[0]
    assert item.waiver_url and "/waiver/" in item.waiver_url and item.waiver_signed is False

    WaiverService(db).sign(item.waiver_url.rsplit("/", 1)[1], _sign_request([]), ip=None, user_agent=None)
    assert order_status(reference, db).items[0].waiver_signed is True


def test_reminder_email_carries_waiver_link_until_signed(db, ghl) -> None:
    op = _operator(db)
    _booking(db, op, _calendar(db, op), units=1, start=_tomorrow(10))
    db.commit()
    ReminderService(db).enqueue()
    OutboxService(db, Settings()).process()
    (message,) = [body for _, path, body in ghl if path == "/conversations/messages"]
    assert "/waiver/" in message["message"] and 'href="' in message["html"]


def test_removing_staff_from_a_slot_emails_them(db, ghl) -> None:
    op = _operator(db)
    cal = _calendar(db, op)
    db.commit()
    service = StaffService(db, op.id)
    staff = service.create_staff(StaffCreate(name="Sam Captain", email="sam@example.com", hours=ALL_WEEK))
    assignment = service.assign(
        StaffAssignmentCreate(staff_id=staff["id"], calendar_id=cal.id, start_at=_tomorrow(9), role="Captain")
    )
    OutboxService(db, Settings()).process()
    ghl.clear()

    service.unassign(assignment["id"])
    OutboxService(db, Settings()).process()
    (message,) = [body for _, path, body in ghl if path == "/conversations/messages"]
    assert message["subject"].startswith("Schedule change: Sunset Cruise on ")
    assert "no longer scheduled for Sunset Cruise as Captain" in message["message"]


def test_removing_staff_without_email_sends_nothing(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op)
    db.commit()
    service = StaffService(db, op.id)
    staff = service.create_staff(StaffCreate(name="Nia", hours=ALL_WEEK))
    assignment = service.assign(StaffAssignmentCreate(staff_id=staff["id"], calendar_id=cal.id, start_at=_tomorrow(9)))
    service.unassign(assignment["id"])
    assert list(db.scalars(select(OutboxJob).where(OutboxJob.job_type == "ghl_staff_unassigned_email"))) == []
