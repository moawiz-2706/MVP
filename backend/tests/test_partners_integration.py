"""Partner tagging through OrderService against a real Postgres (TEST_DATABASE_URL)."""

import os
import uuid
from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.exceptions import ConflictError
from app.models.entities import BookingOrder, Calendar, CalendarHour, Operator, Payment
from app.schemas.order import OrderCreateRequest, OrderCustomer, OrderItemRequest
from app.services.order_service import OrderService
from app.services.partner_service import PartnerService, commission_report, partner_split

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)

SETTINGS = Settings(ghl_notifications_enabled=False, ghl_sync_mode="disabled")


@pytest.fixture()
def shop(db):
    operator = Operator(ghl_location_id=f"loc-{uuid.uuid4().hex}", name="Op", slug=f"op-{uuid.uuid4().hex[:8]}",
                        time_zone="America/New_York", public_booking_enabled=True)
    db.add(operator)
    db.flush()
    calendar = Calendar(operator_id=operator.id, name="Sunset", slug=f"s-{uuid.uuid4().hex[:8]}", duration_minutes=60,
                        slot_interval_minutes=60, base_price_minor=5000, public_booking_enabled=True)
    db.add(calendar)
    db.flush()
    db.add_all([CalendarHour(calendar_id=calendar.id, day_of_week=d, start_time=time(0), end_time=time(23, 59)) for d in range(7)])
    db.commit()
    sunseeker = PartnerService(db, operator.id).create({"name": "Sunseeker"})
    return operator, calendar, sunseeker


def _book(db, operator, calendar, hour, **partner):
    request = OrderCreateRequest(
        items=[OrderItemRequest(calendar_id=calendar.id, start_at=datetime(2027, 1, 4, hour, tzinfo=UTC), units=2)],
        customer=OrderCustomer(first_name="Pat", last_name="Guest", email="pat@example.com"),
        payment_method="none",
        **partner,
    )
    result = OrderService(db, SETTINGS).create(
        operator.slug, request, allow_payment_override=True, allow_partner_selection=True,
    )
    return db.scalar(select(BookingOrder).where(BookingOrder.public_reference == result.public_reference))


def test_link_code_tags_the_booking_and_unknown_codes_book_direct(db, shop):
    operator, calendar, sunseeker = shop
    tagged = _book(db, operator, calendar, 15, partner_code="Sunseeker")
    assert (tagged.partner_id, tagged.partner_name_snapshot, tagged.partner_hotel_bps, tagged.partner_pga_bps) == (
        sunseeker.id, "Sunseeker", 2000, 3000
    )
    direct = _book(db, operator, calendar, 16, partner_code="no-such-hotel")
    assert direct.partner_id is None


def test_staff_choice_requires_an_active_partner(db, shop):
    operator, calendar, sunseeker = shop
    order = _book(db, operator, calendar, 15, partner_id=sunseeker.id)
    assert order.partner_id == sunseeker.id
    PartnerService(db, operator.id).update(sunseeker.id, {"is_active": False})
    with pytest.raises(ConflictError):
        _book(db, operator, calendar, 16, partner_id=sunseeker.id)


def test_rate_change_does_not_rewrite_past_bookings_and_report_groups_by_partner(db, shop):
    operator, calendar, sunseeker = shop
    first = _book(db, operator, calendar, 15, partner_code="sunseeker")
    PartnerService(db, operator.id).update(sunseeker.id, {"hotel_commission_bps": 1000})
    _book(db, operator, calendar, 16)
    payment = db.scalar(select(Payment).where(Payment.booking_order_id == first.id))
    assert partner_split(first, payment).hotel_commission_minor == first.subtotal_minor * 20 // 100
    rows = commission_report(db, operator.id, date(2027, 1, 4), date(2027, 1, 4), operator.time_zone)
    assert [row["source_partner"] for row in rows] == ["Sunseeker", "Direct"]
    assert rows[0]["guests"] == 2 and rows[1]["hotel_commission_minor"] == 0
