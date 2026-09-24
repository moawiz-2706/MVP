"""DB-backed integration tests for the availability engine and its concurrency
guarantee. Gated on ``TEST_DATABASE_URL`` (see conftest). These exercise the
real SQLAlchemy models and PostgreSQL row locks — the parts of the spec test
matrix that cannot be proven with pure-logic tests.

Covered: §153 #7-#17 (availability states) and §154 #18 (row-lock serialization).
"""

import os
import threading
import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import NotFoundError
from app.models.entities import (
    Booking,
    BookingOrder,
    BookingResource,
    Calendar,
    CalendarBlock,
    CalendarHour,
    CalendarResource,
    Operator,
    Resource,
    Staff,
    StaffAssignment,
    StaffHour,
)
from app.services.availability_service import AvailabilityService
from app.utils.timezone import local_datetime

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)

TZ = "America/New_York"
DAY = date(2027, 6, 15)  # a Tuesday


def _operator(db) -> Operator:
    op = Operator(
        ghl_location_id=f"loc-{uuid.uuid4()}",
        name="Punta Gorda Rentals",
        slug=f"op-{uuid.uuid4().hex[:8]}",
        time_zone=TZ,
    )
    db.add(op)
    db.flush()
    return op


def _calendar(db, op, *, duration=180, active=True, deleted=False) -> Calendar:
    cal = Calendar(
        operator_id=op.id,
        name="3-Hour Single Kayak Rental",
        slug=f"cal-{uuid.uuid4().hex[:8]}",
        duration_minutes=duration,
        slot_interval_minutes=30,
        base_price_minor=7000,
        is_active=active,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    db.add(cal)
    db.flush()
    for dow in range(7):  # open every day 08:00-18:00 local
        db.add(
            CalendarHour(
                calendar_id=cal.id, day_of_week=dow, start_time=time(8), end_time=time(18)
            )
        )
    db.flush()
    if active and not deleted:
        captain = Staff(
            operator_id=op.id,
            name="Test Captain",
            custom_role="Captain",
            is_active=True,
        )
        db.add(captain)
        db.flush()
        db.add_all(
            [
                StaffHour(
                    staff_id=captain.id,
                    day_of_week=dow,
                    start_time=time(0),
                    end_time=time(23, 59),
                )
                for dow in range(7)
            ]
        )
        db.add(
            StaffAssignment(
                operator_id=op.id,
                staff_id=captain.id,
                calendar_id=cal.id,
                start_at=local_datetime(DAY, time(0), TZ),
                end_at=local_datetime(DAY + timedelta(days=1), time(0), TZ),
                role="Captain",
            )
        )
    db.flush()
    return cal


def _resource(db, op, *, quantity=15, active=True, deleted=False) -> Resource:
    res = Resource(
        operator_id=op.id,
        name="Single Kayaks",
        quantity=quantity,
        is_active=active,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    db.add(res)
    db.flush()
    return res


def _map(db, cal, res, per_unit=1) -> None:
    db.add(
        CalendarResource(
            calendar_id=cal.id, resource_id=res.id, default_quantity_per_unit=per_unit
        )
    )
    db.flush()


def _booking(db, op, cal, res, *, start, end, qty, status="confirmed", hold=None) -> Booking:
    order = BookingOrder(
        operator_id=op.id,
        public_reference=f"RM-{uuid.uuid4().hex[:12]}",
        customer_first_name="Ada",
        customer_last_name="Lovelace",
        customer_email="ada@example.com",
        subtotal_minor=0,
        platform_fee_and_taxes_minor=0,
        customer_total_minor=0,
        operator_transfer_minor=0,
        platform_gross_retained_minor=0,
        status="pending_payment",
    )
    db.add(order)
    db.flush()
    booking = Booking(
        operator_id=op.id,
        booking_order_id=order.id,
        calendar_id=cal.id,
        start_at=start,
        end_at=end,
        units=qty,
        base_price_minor=7000,
        status=status,
        hold_expires_at=hold,
        calendar_name_snapshot=cal.name,
    )
    db.add(booking)
    db.flush()
    db.add(BookingResource(booking_id=booking.id, resource_id=res.id, quantity=qty))
    db.flush()
    return booking


def _start(hour: int) -> datetime:
    return local_datetime(DAY, time(hour, 0), TZ)


def test_spec153_7_cancelled_booking_frees_inventory(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op)
    res = _resource(db, op, quantity=15)
    _map(db, cal, res)
    _booking(db, op, cal, res, start=_start(10), end=_start(13), qty=15, status="cancelled")
    db.commit()
    result = AvailabilityService(db).check(cal.id, _start(10), 4, operator_id=op.id)
    assert result.available  # cancelled holds nothing


def test_staff_or_role_availability_does_not_block_calendar_slot(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op)
    res = _resource(db, op, quantity=2)
    _map(db, cal, res)
    staff = db.scalar(select(Staff).where(Staff.operator_id == op.id))
    assert staff is not None
    staff.is_active = False
    staff.custom_role = "Unavailable Role"
    db.commit()

    result = AvailabilityService(db).check(cal.id, _start(10), 1, operator_id=op.id)

    assert result.available
    assert result.max_bookable_units == 2


def test_spec153_8_unexpired_hold_consumes_inventory(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op)
    res = _resource(db, op, quantity=15)
    _map(db, cal, res)
    _booking(
        db, op, cal, res,
        start=_start(10), end=_start(13), qty=15,
        status="pending_payment", hold=datetime.now(UTC) + timedelta(minutes=10),
    )
    db.commit()
    result = AvailabilityService(db).check(cal.id, _start(10), 4, operator_id=op.id)
    assert not result.available


def test_spec153_9_expired_hold_frees_inventory(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op)
    res = _resource(db, op, quantity=15)
    _map(db, cal, res)
    _booking(
        db, op, cal, res,
        start=_start(10), end=_start(13), qty=15,
        status="pending_payment", hold=datetime.now(UTC) - timedelta(minutes=1),
    )
    db.commit()
    result = AvailabilityService(db).check(cal.id, _start(10), 4, operator_id=op.id)
    assert result.available  # expired hold ignored without any cleanup job


def test_spec153_10_block_makes_slot_unavailable(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op)
    res = _resource(db, op, quantity=15)
    _map(db, cal, res)
    db.add(
        CalendarBlock(calendar_id=cal.id, start_at=_start(9), end_at=_start(12), reason="maintenance")
    )
    db.commit()
    result = AvailabilityService(db).check(cal.id, _start(10), 1, operator_id=op.id)
    assert not result.available
    assert result.reason == "Requested time is blocked"


def test_spec153_11_outside_hours_unavailable(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op)
    res = _resource(db, op, quantity=15)
    _map(db, cal, res)
    db.commit()
    result = AvailabilityService(db).check(cal.id, _start(6), 1, operator_id=op.id)  # 06:00, before open
    assert not result.available


def test_spec153_12_booking_past_closing_unavailable(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op, duration=180)
    res = _resource(db, op, quantity=15)
    _map(db, cal, res)
    db.commit()
    result = AvailabilityService(db).check(cal.id, _start(16), 1, operator_id=op.id)  # 16:00 -> 19:00
    assert not result.available


def test_spec153_13_shared_resource_across_calendars(db) -> None:
    op = _operator(db)
    res = _resource(db, op, quantity=15)
    cal_a = _calendar(db, op)
    cal_b = _calendar(db, op)
    _map(db, cal_a, res)
    _map(db, cal_b, res)
    _booking(db, op, cal_b, res, start=_start(9), end=_start(12), qty=6)  # consumes on B
    db.commit()
    engine = AvailabilityService(db)
    assert engine.check(cal_a.id, _start(10), 9, operator_id=op.id).available
    assert not engine.check(cal_a.id, _start(10), 10, operator_id=op.id).available


def test_spec153_15_inactive_resource_blocks_booking(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op)
    res = _resource(db, op, quantity=15, active=False)
    _map(db, cal, res)
    db.commit()
    result = AvailabilityService(db).check(cal.id, _start(10), 1, operator_id=op.id)
    assert not result.available


def test_spec153_16_deleted_calendar_not_found(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op, deleted=True)
    db.commit()
    with pytest.raises(NotFoundError):
        AvailabilityService(db).check(cal.id, _start(10), 1, operator_id=op.id)


def test_spec153_17_cross_operator_resource_rejected(db) -> None:
    op = _operator(db)
    other = _operator(db)
    cal = _calendar(db, op)
    db.commit()
    # Passing another operator's id must not resolve this calendar.
    with pytest.raises(NotFoundError):
        AvailabilityService(db).check(cal.id, _start(10), 1, operator_id=other.id)


def test_all_attached_resources_are_required(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op)
    boat = _resource(db, op, quantity=2)
    equipment = _resource(db, op, quantity=2)
    _map(db, cal, boat)
    _map(db, cal, equipment)
    db.commit()

    engine = AvailabilityService(db)
    assert engine.check(cal.id, _start(10), 1, operator_id=op.id).available

    # Occupying only one shared component makes the complete calendar slot
    # unavailable even though the other attached resource still has capacity.
    _booking(db, op, cal, equipment, start=_start(10), end=_start(13), qty=2)
    db.commit()
    result = engine.check(cal.id, _start(10), 1, operator_id=op.id)
    assert not result.available
    assert result.reason == "Insufficient resource inventory"


def test_required_staff_role_availability_does_not_block_booking(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op)
    cal.required_staff_roles = ["Captain", "First Mate"]
    res = _resource(db, op)
    _map(db, cal, res)
    first_mate = Staff(
        operator_id=op.id,
        name="Test First Mate",
        custom_role="First Mate",
        is_active=True,
    )
    db.add(first_mate)
    db.flush()
    db.add_all(
        [
            StaffHour(
                staff_id=first_mate.id,
                day_of_week=dow,
                start_time=time(0),
                end_time=time(23, 59),
            )
            for dow in range(7)
        ]
    )
    db.commit()

    engine = AvailabilityService(db)
    assert engine.check(cal.id, _start(10), 1, operator_id=op.id).available

    first_mate.is_active = False
    db.commit()
    result = engine.check(cal.id, _start(10), 1, operator_id=op.id)
    assert result.available


def test_spec154_18_row_lock_serializes_last_unit(engine) -> None:
    # Resource quantity 1; two threads race for the same overlapping slot.
    # The FOR UPDATE lock must let exactly one reservation commit.
    maker = sessionmaker(engine, expire_on_commit=False, future=True)
    setup = maker()
    op = _operator(setup)
    cal = _calendar(setup, op)
    res = _resource(setup, op, quantity=1)
    _map(setup, cal, res)
    setup.commit()
    resource_id, cal_id, op_id = res.id, cal.id, op.id
    setup.close()

    start, end = _start(10), _start(13)
    barrier = threading.Barrier(2)
    outcomes: list[bool] = []
    lock = threading.Lock()

    def attempt() -> None:
        session = maker()
        try:
            session.begin()
            barrier.wait(timeout=10)
            # Serialize on the resource row exactly like OrderService does.
            session.execute(select(Resource).where(Resource.id == resource_id).with_for_update()).scalar_one()
            ok = AvailabilityService(session).check(cal_id, start, 1, operator_id=op_id).available
            if ok:
                _booking(session, op, cal, res, start=start, end=end, qty=1)
                session.commit()
            else:
                session.rollback()
            with lock:
                outcomes.append(ok)
        finally:
            session.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert sorted(outcomes) == [False, True]  # exactly one winner
    check = maker()
    try:
        # Exactly one reservation landed against the single-unit pool.
        held = check.scalars(select(Booking).where(Booking.calendar_id == cal_id)).all()
        assert len(held) == 1
    finally:
        check.close()
