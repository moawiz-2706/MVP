import os
import uuid
from datetime import UTC, datetime, time

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.reports import bookings_by_creator
from app.core.app_session import SessionPrincipal
from app.core.config import Settings
from app.models.entities import AppUser, BookingOrder, Calendar, CalendarHour, Operator, Staff
from app.schemas.order import OrderCreateRequest, OrderCustomer, OrderItemRequest
from app.services.attribution import staff_attribution
from app.services.booking_admin_service import BookingAdminService
from app.services.order_service import BookingAttribution, OrderService

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)

SETTINGS = Settings(ghl_notifications_enabled=False, ghl_sync_mode="disabled")


@pytest.fixture()
def shop(db):
    operator = Operator(ghl_location_id=f"loc-{uuid.uuid4().hex}", name="Op", slug=f"op-{uuid.uuid4().hex[:8]}",
                        time_zone="UTC", public_booking_enabled=True)
    db.add(operator)
    db.flush()
    calendar = Calendar(operator_id=operator.id, name="Tour", slug=f"t-{uuid.uuid4().hex[:8]}", duration_minutes=60,
                        slot_interval_minutes=60, base_price_minor=5000, public_booking_enabled=True)
    db.add(calendar)
    db.flush()
    db.add_all([CalendarHour(calendar_id=calendar.id, day_of_week=d, start_time=time(0), end_time=time(23, 59)) for d in range(7)])
    seller = AppUser(ghl_user_id=f"ghl-{uuid.uuid4().hex[:8]}", email="seller@example.com", name="Sam Seller")
    db.add(seller)
    db.flush()
    seller_staff = Staff(operator_id=operator.id, name="Sam (staff)", is_active=True, ghl_user_id=seller.ghl_user_id)
    guide = Staff(operator_id=operator.id, name="Gale Guide", is_active=True)
    db.add_all([seller_staff, guide])
    db.commit()
    return operator, calendar, seller, seller_staff, guide


def _book(db, operator, calendar, hour, attribution):
    request = OrderCreateRequest(
        items=[OrderItemRequest(calendar_id=calendar.id, start_at=datetime(2027, 1, 4, hour, tzinfo=UTC), units=1)],
        customer=OrderCustomer(first_name="Pat", last_name="Guest", email="pat@example.com"),
        payment_required=False,
    )
    result = OrderService(db, SETTINGS).create(operator.slug, request, allow_payment_override=True, attribution=attribution)
    return db.scalar(select(BookingOrder).where(BookingOrder.public_reference == result.public_reference))


def _principal(operator, user, role="user"):
    return SessionPrincipal(app_user_id=user.id, operator_id=operator.id, ghl_location_id=operator.ghl_location_id,
                            role=role, is_agency_owner=False)


def test_every_path_records_source_and_creator_separately_from_assignment(db, shop):
    operator, calendar, seller, seller_staff, guide = shop
    public = _book(db, operator, calendar, 9, None)
    link = _book(db, operator, calendar, 10, BookingAttribution(source="staff_link", created_by_staff_id=guide.id))
    pwa = _book(db, operator, calendar, 11, staff_attribution(db, _principal(operator, seller), "pwa"))
    desktop = _book(db, operator, calendar, 12, staff_attribution(db, _principal(operator, seller), None))

    assert (public.booking_source, public.created_by_user_id, public.created_by_staff_id) == ("public", None, None)
    assert (link.booking_source, link.created_by_staff_id) == ("staff_link", guide.id)
    # The signed-in user's own staff record is found through the shared HighLevel user.
    assert (pwa.booking_source, pwa.created_by_user_id, pwa.created_by_staff_id) == ("pwa", seller.id, seller_staff.id)
    assert desktop.booking_source == "desktop"

    booking_id = db.scalar(select(BookingOrder.id).where(BookingOrder.id == pwa.id))
    from app.models.entities import Booking

    detail = BookingAdminService(db, operator.id).detail(
        db.scalar(select(Booking.id).where(Booking.booking_order_id == booking_id))
    )
    assert detail["created_by_name"] == "Sam (staff)" and detail["booking_source"] == "pwa"


def test_creator_report_groups_by_creator_and_is_admin_only(db, shop):
    operator, calendar, seller, seller_staff, guide = shop
    _book(db, operator, calendar, 9, None)
    _book(db, operator, calendar, 10, BookingAttribution(source="staff_link", created_by_staff_id=guide.id))
    _book(db, operator, calendar, 11, BookingAttribution(source="staff_link", created_by_staff_id=guide.id))
    _book(db, operator, calendar, 12, staff_attribution(db, _principal(operator, seller), "pwa"))

    with pytest.raises(HTTPException) as denied:
        bookings_by_creator(principal=_principal(operator, seller), db=db, start_date=None, end_date=None)
    assert denied.value.status_code == 403

    report = bookings_by_creator(principal=_principal(operator, seller, role="admin"), db=db, start_date=None, end_date=None)
    by_name = {row.creator_name: row for row in report.rows}
    assert by_name["Gale Guide"].orders == 2 and by_name["Gale Guide"].booking_source == "staff_link"
    assert by_name["Sam (staff)"].orders == 1 and by_name["Sam (staff)"].booking_source == "pwa"
    assert by_name["Public booking page"].orders == 1
    assert all(row.confirmed_orders == row.orders for row in report.rows)  # free bookings confirm immediately
