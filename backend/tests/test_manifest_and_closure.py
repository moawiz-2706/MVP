import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.v1.pwa import departure_closure_preview
from app.core.app_session import SessionPrincipal
from app.core.exceptions import ConflictError
from app.models.entities import (
    AppUser,
    Booking,
    BookingEvent,
    BookingOrder,
    BookingParticipant,
    CalendarBlock,
    OutboxJob,
    Payment,
    PaymentRefundAttempt,
    WeatherClosureEvent,
)
from app.schemas.pwa import PWACloseDepartureRequest
from app.services.manifest_service import ManifestService
from app.services.weather_closure import close_departure, closure_preview
from tests.test_lifecycle_hardening import _paid_booking
from tests.test_waivers_integration import _booking

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)


def _staff_user(db, operator):
    user = AppUser(ghl_user_id=f"u-{uuid.uuid4().hex[:8]}", email="staff@example.com", name="Staff")
    db.add(user)
    db.commit()
    return user


def _participants(db, booking, *people):
    rows = []
    for sequence, (first, minor, guardian) in enumerate(people, start=1):
        row = BookingParticipant(operator_id=booking.operator_id, booking_id=booking.id, sequence=sequence,
                                 first_name=first, last_name="Guest", is_minor=minor, guardian_name=guardian)
        db.add(row)
        rows.append(row)
    db.commit()
    return rows


def _departure(db):
    operator, calendar, first, _order, _payment = _paid_booking(db)
    second = _booking(db, operator, calendar, units=2, start=first.start_at)
    cancelled = _booking(db, operator, calendar, units=5, start=first.start_at, status="cancelled")
    db.commit()
    return operator, calendar, first, second, cancelled


def test_manifest_lists_active_parties_people_and_waiver_state(db):
    operator, calendar, first, second, _cancelled = _departure(db)
    _participants(db, first, ("Ana", False, None), ("Ben", True, "Ana Guest"))

    manifest = ManifestService(db, operator.id).manifest(calendar.id, first.start_at)
    assert [booking.id for booking in manifest.bookings] and len(manifest.bookings) == 2  # cancelled excluded
    assert manifest.expected_units == first.units + second.units
    assert manifest.named_participants == 2 and manifest.checked_in == 0
    minor = next(p for b in manifest.bookings for p in b.participants if p.is_minor)
    assert minor.guardian_name == "Ana Guest"
    assert {b.waiver_status for b in manifest.bookings} <= {"none", "pending", "signed"}


def test_check_in_is_idempotent_audited_and_reversible(db):
    operator, calendar, first, _second, cancelled = _departure(db)
    ana, _ben = _participants(db, first, ("Ana", False, None), ("Ben", True, "Ana Guest"))
    user = _staff_user(db, operator)
    service = ManifestService(db, operator.id)

    stamped = service.set_check_in(ana.id, True, user.id)
    again = service.set_check_in(ana.id, True, user.id)  # double tap
    assert stamped.checked_in_at is not None and again.checked_in_at == stamped.checked_in_at
    events = lambda kind: db.scalar(select(func.count()).select_from(BookingEvent).where(  # noqa: E731
        BookingEvent.booking_id == first.id, BookingEvent.event_type == kind))
    assert events("participant_checked_in") == 1
    db.refresh(ana)
    assert ana.checked_in_by_user_id == user.id
    assert service.manifest(calendar.id, first.start_at).checked_in == 1

    assert service.set_check_in(ana.id, False, user.id).checked_in_at is None
    assert events("participant_check_in_undone") == 1

    (ghost,) = _participants(db, cancelled, ("Gus", False, None))
    with pytest.raises(ConflictError):
        service.set_check_in(ghost.id, True, user.id)


def test_other_operators_cannot_check_in_or_read_the_manifest(db):
    operator, calendar, first, _second, _cancelled = _departure(db)
    (ana,) = _participants(db, first, ("Ana", False, None))
    stranger, *_ = _paid_booking(db)
    user = _staff_user(db, stranger)
    with pytest.raises(Exception):
        ManifestService(db, stranger.id).set_check_in(ana.id, True, user.id)
    with pytest.raises(Exception):
        ManifestService(db, stranger.id).manifest(calendar.id, first.start_at)


def test_closure_preview_is_admin_only(db):
    operator, calendar, first, _second, _cancelled = _departure(db)
    user = _staff_user(db, operator)
    staff = SessionPrincipal(app_user_id=user.id, operator_id=operator.id, ghl_location_id=operator.ghl_location_id,
                             role="user", is_agency_owner=False)
    with pytest.raises(HTTPException) as denied:
        departure_closure_preview(principal=staff, db=db, calendar_id=calendar.id, start_at=first.start_at)
    assert denied.value.status_code == 403


def test_close_departure_requires_a_current_preview_then_is_safe_to_retry(db):
    operator, calendar, first, second, _cancelled = _departure(db)
    user = _staff_user(db, operator)
    preview = closure_preview(db, operator.id, calendar.id, first.start_at)
    assert len(preview.manifest.bookings) == 2 and not preview.already_closed

    request = PWACloseDepartureRequest(calendar_id=calendar.id, start_at=first.start_at, reason="Lightning",
                                       refund_mode=preview.default_refund_mode, expected_bookings=1)
    with pytest.raises(ConflictError):
        close_departure(db, operator.id, user.id, request)  # the preview the operator saw is stale

    request.expected_bookings = 2
    result = close_departure(db, operator.id, user.id, request)
    assert result.cancelled_bookings == 2 and result.failed == []
    for booking in (first, second):
        db.refresh(booking)
        assert booking.status == "cancelled"
    closure = db.get(WeatherClosureEvent, result.closure_id)
    assert closure.created_by_user_id == user.id and closure.reason == "Lightning"

    def counts():
        return (
            db.scalar(select(func.count()).select_from(PaymentRefundAttempt)),
            db.scalar(select(func.count()).select_from(OutboxJob).where(OutboxJob.job_type == "ghl_booking_weather_email")),
            db.scalar(select(func.count()).select_from(CalendarBlock).where(CalendarBlock.calendar_id == calendar.id)),
        )

    before = counts()
    assert before[0] == 1  # the paid party is refunded once; the free party has nothing to refund
    assert before[2] == 1  # new sales for the interval are blocked
    retry = close_departure(db, operator.id, user.id, request)
    assert retry.cancelled_bookings == 0 and retry.closure_id == result.closure_id
    assert counts() == before  # no second refund, message or block
    assert closure_preview(db, operator.id, calendar.id, first.start_at).already_closed
