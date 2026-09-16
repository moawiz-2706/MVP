"""DB-backed tests for staff assignment to calendar time slots.

A staff member may only be assigned inside their weekly working hours, and is
busy for the whole slot across every calendar. Gated on TEST_DATABASE_URL.
"""

import os
import threading
import uuid
from datetime import date, time, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import ConflictError
from app.models.entities import Calendar, Operator, Staff, StaffAssignment, StaffHour
from app.schemas.staff import StaffAssignmentCreate, StaffCreate, StaffHourWrite, StaffUpdate
from app.services.booking_admin_service import BookingAdminService
from app.services.staff_service import StaffService
from app.utils.timezone import local_datetime

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)

TZ = "America/New_York"
DAY = date(2027, 6, 15)  # Tuesday -> day_of_week 1


def _at(hour: int, minute: int = 0):
    return local_datetime(DAY, time(hour, minute), TZ)


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


def _calendar(db, op, name: str = "Sunset Cruise", duration: int = 180) -> Calendar:
    cal = Calendar(
        operator_id=op.id,
        name=name,
        slug=f"cal-{uuid.uuid4().hex[:8]}",
        duration_minutes=duration,
        base_price_minor=0,
    )
    db.add(cal)
    db.flush()
    return cal


def _staff(db, op, name: str = "Sam", hours=((1, 8, 18),), active: bool = True) -> Staff:
    staff = Staff(operator_id=op.id, name=name, is_active=active)
    db.add(staff)
    db.flush()
    for day, opens, closes in hours:
        db.add(StaffHour(staff_id=staff.id, day_of_week=day, start_time=time(opens), end_time=time(closes)))
    db.flush()
    return staff


def _assign(service: StaffService, staff, cal, start, role: str | None = "Captain"):
    return service.assign(
        StaffAssignmentCreate(staff_id=staff.id, calendar_id=cal.id, start_at=start, role=role)
    )


def test_assign_inside_hours_sets_end_from_duration_and_role(db) -> None:
    op = _operator(db)
    cal, staff = _calendar(db, op), _staff(db, op)
    db.commit()
    result = _assign(StaffService(db, op.id), staff, cal, _at(9))
    assert result["end_at"] == _at(12)
    assert result["role"] == "Captain"


def test_assign_outside_working_hours_is_rejected(db) -> None:
    op = _operator(db)
    cal, staff = _calendar(db, op), _staff(db, op, hours=[(1, 8, 11)])
    db.commit()
    with pytest.raises(ConflictError, match="not working"):
        _assign(StaffService(db, op.id), staff, cal, _at(9))  # 09:00-12:00 runs past 11:00


def test_staff_is_busy_across_calendars(db) -> None:
    op = _operator(db)
    cruise, tour = _calendar(db, op), _calendar(db, op, name="Kayak Tour", duration=60)
    staff = _staff(db, op)
    db.commit()
    service = StaffService(db, op.id)
    _assign(service, staff, cruise, _at(9))  # busy 09:00-12:00
    with pytest.raises(ConflictError, match="already assigned to Sunset Cruise"):
        _assign(service, staff, tour, _at(11))


def test_touching_slots_do_not_conflict(db) -> None:
    op = _operator(db)
    cal, staff = _calendar(db, op), _staff(db, op)
    db.commit()
    service = StaffService(db, op.id)
    _assign(service, staff, cal, _at(9))
    _assign(service, staff, cal, _at(12))  # starts exactly when the first ends


def test_inactive_staff_cannot_be_assigned(db) -> None:
    op = _operator(db)
    cal, staff = _calendar(db, op), _staff(db, op, active=False)
    db.commit()
    with pytest.raises(ConflictError, match="inactive"):
        _assign(StaffService(db, op.id), staff, cal, _at(9))


def test_candidates_flag_who_can_take_a_slot(db) -> None:
    op = _operator(db)
    cal = _calendar(db, op)
    free, busy, off = _staff(db, op, "Ana"), _staff(db, op, "Ben"), _staff(db, op, "Cy", hours=[])
    db.commit()
    service = StaffService(db, op.id)
    _assign(service, busy, _calendar(db, op, name="Other"), _at(10))
    by_name = {c["name"]: c for c in service.candidates(cal.id, _at(9))}
    assert by_name["Ana"]["available"] is True
    assert by_name["Ben"]["available"] is False and "already assigned" in by_name["Ben"]["reason"]
    assert by_name["Cy"]["available"] is False and "not working" in by_name["Cy"]["reason"]


def test_staff_crud_round_trips_split_shift_hours(db) -> None:
    op = _operator(db)
    db.commit()
    service = StaffService(db, op.id)
    created = service.create_staff(
        StaffCreate(
            name="Sam",
            hours=[
                StaffHourWrite(day_of_week=1, start_time=time(8), end_time=time(12)),
                StaffHourWrite(day_of_week=1, start_time=time(13), end_time=time(17)),
            ],
        )
    )
    assert len(created["hours"]) == 2
    updated = service.update_staff(
        created["id"],
        StaffUpdate(hours=[StaffHourWrite(day_of_week=3, start_time=time(9), end_time=time(10))]),
    )
    assert [(h["day_of_week"], h["start_time"]) for h in updated["hours"]] == [(3, time(9))]


def test_delete_staff_releases_future_assignments(db) -> None:
    op = _operator(db)
    cal, staff = _calendar(db, op), _staff(db, op)
    db.commit()
    service = StaffService(db, op.id)
    _assign(service, staff, cal, _at(9))
    service.delete_staff(staff.id)
    assert db.scalar(select(StaffAssignment).where(StaffAssignment.staff_id == staff.id)) is None
    assert service.list_staff() == []


def test_dashboard_slot_carries_staff_and_role(db) -> None:
    op = _operator(db)
    cal, staff = _calendar(db, op), _staff(db, op)
    db.commit()
    _assign(StaffService(db, op.id), staff, cal, _at(9), role="First Mate")
    slots = BookingAdminService(db, op.id).slots(_at(0), _at(23))
    assert len(slots) == 1 and slots[0]["start_at"] == _at(9)
    entry = slots[0]["calendars"][0]
    assert entry["calendar_name"] == "Sunset Cruise"
    assert [(s["staff_name"], s["role"]) for s in entry["staff"]] == [("Sam", "First Mate")]


def test_concurrent_assignments_of_one_person_serialize(engine) -> None:
    """Two sessions assign the same person to overlapping slots at once: one wins."""
    maker = sessionmaker(engine, expire_on_commit=False, future=True)
    with maker() as setup:
        op = _operator(setup)
        cruise, tour = _calendar(setup, op), _calendar(setup, op, name="Kayak Tour")
        staff = _staff(setup, op)
        setup.commit()
        op_id, staff_id, calendar_ids = op.id, staff.id, [cruise.id, tour.id]

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt(calendar_id) -> None:
        with maker() as session:
            barrier.wait()
            try:
                StaffService(session, op_id).assign(
                    StaffAssignmentCreate(staff_id=staff_id, calendar_id=calendar_id, start_at=_at(9))
                )
                outcome = "ok"
            except ConflictError:
                session.rollback()
                outcome = "conflict"
            with lock:
                outcomes.append(outcome)

    threads = [threading.Thread(target=attempt, args=(cid,)) for cid in calendar_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(outcomes) == ["conflict", "ok"]
    with maker() as check:
        assert len(list(check.scalars(select(StaffAssignment)))) == 1
