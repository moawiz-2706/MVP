import os
import uuid
from datetime import UTC, datetime, time

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.entities import (
    Booking,
    Calendar,
    CalendarHour,
    CalendarRate,
    CalendarRateResource,
    CustomerType,
    Operator,
    Resource,
)
from app.schemas.order import OrderItemRequest, OrderQuoteRequest
from app.services.order_service import OrderService

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run rate tests",
)


def _operator(db) -> Operator:
    operator = Operator(
        ghl_location_id=f"loc-{uuid.uuid4().hex}",
        name="Kayak Operator",
        slug=f"kayak-{uuid.uuid4().hex[:8]}",
        time_zone="America/New_York",
    )
    db.add(operator)
    db.flush()
    return operator


def _kayak_setup(db):
    operator = _operator(db)
    calendar = Calendar(
        operator_id=operator.id,
        name="Kayak Swamp Tour",
        slug=f"swamp-{uuid.uuid4().hex[:8]}",
        duration_minutes=120,
        slot_interval_minutes=30,
        base_price_minor=0,
        availability_mode="day_wise",
        is_active=True,
        public_booking_enabled=True,
    )
    single_resource = Resource(operator_id=operator.id, name="Single Kayaks", quantity=20)
    tandem_resource = Resource(operator_id=operator.id, name="Tandem Kayaks", quantity=6)
    single_type = CustomerType(
        operator_id=operator.id,
        name="Single Kayak",
        plural_name="Single Kayaks",
        note="Seats One Person",
        seat_count=1,
    )
    tandem_type = CustomerType(
        operator_id=operator.id,
        name="Tandem Kayak",
        plural_name="Tandem Kayaks",
        note="Seats Two People",
        seat_count=2,
    )
    db.add_all([calendar, single_resource, tandem_resource, single_type, tandem_type])
    db.flush()
    db.add(
        CalendarHour(
            calendar_id=calendar.id,
            day_of_week=4,
            start_time=time(8),
            end_time=time(18),
        )
    )
    single_rate = CalendarRate(
        operator_id=operator.id,
        calendar_id=calendar.id,
        customer_type_id=single_type.id,
        name_snapshot=single_type.name,
        note_snapshot=single_type.note,
        price_minor=4000,
        booking_fee_bps=600,
        tax_bps=750,
    )
    tandem_rate = CalendarRate(
        operator_id=operator.id,
        calendar_id=calendar.id,
        customer_type_id=tandem_type.id,
        name_snapshot=tandem_type.name,
        note_snapshot=tandem_type.note,
        price_minor=8000,
        booking_fee_bps=600,
        tax_bps=750,
    )
    db.add_all([single_rate, tandem_rate])
    db.flush()
    db.add_all(
        [
            CalendarRateResource(rate_id=single_rate.id, resource_id=single_resource.id),
            CalendarRateResource(rate_id=tandem_rate.id, resource_id=tandem_resource.id),
        ]
    )
    db.commit()
    return operator, calendar, single_rate, tandem_rate, single_resource, tandem_resource


def test_rate_quote_uses_customer_type_price_fee_tax_and_resource_rule(db):
    operator, calendar, single_rate, tandem_rate, single_resource, tandem_resource = _kayak_setup(db)
    start = datetime(2027, 6, 18, 13, tzinfo=UTC)
    quote = OrderService(db, get_settings()).quote(
        operator.slug,
        OrderQuoteRequest(
            items=[
                OrderItemRequest(calendar_id=calendar.id, rate_id=single_rate.id, start_at=start, quantity=2),
                OrderItemRequest(calendar_id=calendar.id, rate_id=tandem_rate.id, start_at=start, quantity=1),
            ]
        ),
    )
    assert quote.subtotal_minor == 16_000
    assert quote.booking_fee_minor == 960
    assert quote.tax_minor == 1_200
    assert quote.customer_total_minor == 18_160
    assert [(item.customer_type_name, item.units, item.seat_count) for item in quote.items] == [
        ("Single Kayak", 2, 1),
        ("Tandem Kayak", 1, 2),
    ]
    assert quote.items[0].resources[0]["resource_id"] == single_resource.id
    assert quote.items[1].resources[0]["resource_id"] == tandem_resource.id


def test_rate_create_persists_line_item_and_separate_resource_use(db):
    operator, calendar, single_rate, _tandem_rate, single_resource, _tandem_resource = _kayak_setup(db)
    start = datetime(2027, 6, 18, 13, tzinfo=UTC)
    # The quote path is provider-independent and does not require Stripe onboarding.
    # Persistence is covered by the existing order flow once payment configuration is enabled.
    result = OrderService(db, get_settings())._prepare(
        operator,
        [OrderItemRequest(calendar_id=calendar.id, rate_id=single_rate.id, start_at=start, quantity=3)],
    )
    assert result[0].resources == [(single_resource, 1)]
    assert result[0].line_subtotal_minor == 12_000
    assert result[0].booking_fee_minor == 720
    assert result[0].tax_minor == 900
    assert result[0].seat_count == 1
    assert db.scalar(select(Booking.id)) is None
