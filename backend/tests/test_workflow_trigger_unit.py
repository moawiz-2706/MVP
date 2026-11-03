"""Marketplace Custom Trigger: payload, filters and callback validation (no database)."""

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.entities import (
    Booking,
    BookingLineItem,
    BookingWaiver,
    Operator,
    OperatorSettings,
    OutboxJob,
    Payment,
    Staff,
)
from app.services.ghl_workflow_trigger_service import (
    SECRET_HEADER,
    WorkflowTriggerDeliveryService,
    build_snapshot,
    enqueue_workflow_event,
    format_amount,
    is_execute_url,
    iso_utc,
    matches_filters,
    redact_error,
)

ROOT = Path(__file__).resolve().parents[2]
TARGET = "https://services.leadconnectorhq.com/workflows-marketplace/triggers/execute/abc/def"
# The published v1.0 sample: every top-level key and its JSON type.
PUBLISHED_TYPES = {
    "event_type": str, "schema_version": str, "event_id": str, "idempotency_key": str,
    "occurred_at": str, "source": str, "location_id": str, "booking_order_id": str,
    "public_reference": str, "booking_status": str, "payment_status": str,
    "payment_method": str, "confirmed": bool, "currency": str, "subtotal_amount": str,
    "fees_and_taxes_amount": str, "customer_total_amount": str, "customer_first_name": str,
    "customer_last_name": str, "customer_full_name": str, "customer_email": str,
    "customer_phone": str, "ghl_contact_id": str, "calendar_name": str, "calendar_id": str,
    "start_at": str, "end_at": str, "timezone": str, "location_name": str,
    "waiver_required": bool, "waiver_status": str, "waiver_url": str, "staff_names": str,
    "items": list,
}
UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MONEY = re.compile(r"^\d+\.\d{2}$")


class FakeSession:
    """Answers the handful of queries the payload builder makes."""

    def __init__(self, *, operator, settings, payment, bookings, lines, waivers, staff_names):
        self.operator, self.settings, self.payment = operator, settings, payment
        self.bookings, self.lines, self.waivers, self.staff_names = bookings, lines, waivers, staff_names

    def get(self, model, _id):
        return {Operator: self.operator, OperatorSettings: self.settings}.get(model)

    @staticmethod
    def _entity(statement):
        return statement.column_descriptions[0]["entity"]

    def scalar(self, statement):
        entity = self._entity(statement)
        if entity is Payment:
            return self.payment
        if entity is BookingWaiver:
            booking_id = statement.whereclause.right.value
            return self.waivers.get(booking_id)
        raise AssertionError(f"unexpected scalar query on {entity}")

    def scalars(self, statement):
        entity = self._entity(statement)
        if entity is Booking:
            return list(self.bookings)
        if entity is BookingLineItem:
            return [line for lines in self.lines.values() for line in lines]
        if entity is Staff:
            return list(self.staff_names)
        raise AssertionError(f"unexpected scalars query on {entity}")


def _scenario(
    *,
    method="card",
    order_status="pending_payment",
    payment_status="requires_payment",
    booking_status="pending_payment",
    phone="+15555550123",
    waiver_text="Release of liability",
    waiver_status="pending",
    second_booking=False,
    staff=("Jordan Lee",),
):
    operator = SimpleNamespace(id=uuid.uuid4(), ghl_location_id="ghl-location-id", time_zone="America/New_York")
    order = SimpleNamespace(
        id=uuid.uuid4(), operator_id=operator.id, public_reference="PS-DEMO1234",
        status=order_status, currency="usd", subtotal_minor=10_000,
        platform_fee_and_taxes_minor=1_300, customer_total_minor=11_300,
        customer_first_name="Alex", customer_last_name="Smith",
        customer_email="alex@example.com", customer_phone=phone,
        ghl_contact_id="existing-ghl-contact-id",
    )
    calendar_id = uuid.uuid4()

    def booking(start_hour, name, location):
        return SimpleNamespace(
            id=uuid.uuid4(), operator_id=operator.id, booking_order_id=order.id,
            calendar_id=calendar_id if name == "Sunset Boat Tour" else uuid.uuid4(),
            calendar_name_snapshot=name, departure_location_name_snapshot=location,
            start_at=datetime(2026, 10, 25, start_hour, tzinfo=UTC),
            end_at=datetime(2026, 10, 25, start_hour + 2, tzinfo=UTC),
            status=booking_status, units=2, customer_type_name_snapshot=None,
            line_subtotal_minor=10_000, base_price_minor=5_000,
        )

    bookings = [booking(15, "Sunset Boat Tour", "Main Marina")]
    if second_booking:
        bookings.append(booking(18, "Kayak Rentals", "North Dock"))
    lines = {
        bookings[0].id: [
            SimpleNamespace(booking_id=bookings[0].id, customer_type_name_snapshot="Adult ticket",
                            quantity=2, line_subtotal_minor=10_000),
        ]
    }
    waivers = {}
    if waiver_status in {"pending", "signed"}:
        for index, item in enumerate(bookings):
            token = "demo-token" if index == 0 else f"demo-token-{index}"
            waivers[item.id] = SimpleNamespace(token=token, status=waiver_status, signed_at=None)
    payment = SimpleNamespace(status=payment_status, payment_method=method)
    db = FakeSession(
        operator=operator,
        settings=SimpleNamespace(waiver_text=waiver_text),
        payment=payment,
        bookings=bookings,
        lines=lines,
        waivers=waivers,
        staff_names=list(staff),
    )
    return db, operator, order, bookings


def _payload(db, operator, order, event_type="booking_created", focus=None):
    snapshot = build_snapshot(db, order, focus_booking_id=focus)
    event = SimpleNamespace(
        event_type=event_type,
        event_id=f"{order.id}:{event_type}:v1",
        idempotency_key=f"booking_order:{order.id}:workflow:{event_type}:v1",
        occurred_at=datetime(2026, 10, 23, 12, tzinfo=UTC),
        snapshot=json.loads(json.dumps(snapshot)),  # as stored in JSONB
    )
    service = WorkflowTriggerDeliveryService(db, operator.id, Settings())
    return service.build_payload(event, order)


def _assert_published_shape(payload):
    assert list(payload) == list(PUBLISHED_TYPES), "keys must match the published v1.0 sample"
    for key, kind in PUBLISHED_TYPES.items():
        assert isinstance(payload[key], kind), key
    for key in ("occurred_at", "start_at", "end_at"):
        assert UTC_Z.match(payload[key]), key
    for key in ("subtotal_amount", "fees_and_taxes_amount", "customer_total_amount"):
        assert MONEY.match(payload[key]), key


def test_paid_confirmation_matches_published_sample():
    db, operator, order, bookings = _scenario(
        order_status="confirmed", payment_status="succeeded", booking_status="confirmed"
    )
    payload = _payload(db, operator, order, "booking_confirmed")
    _assert_published_shape(payload)
    assert payload["confirmed"] is True
    assert payload["booking_status"] == "confirmed"
    assert payload["payment_status"] == "succeeded"
    assert payload["payment_method"] == "card"
    assert payload["location_id"] == "ghl-location-id"
    assert payload["ghl_contact_id"] == "existing-ghl-contact-id"
    assert payload["currency"] == "USD"
    assert (payload["subtotal_amount"], payload["fees_and_taxes_amount"], payload["customer_total_amount"]) == (
        "100.00", "13.00", "113.00"
    )
    assert payload["calendar_id"] == str(bookings[0].calendar_id)
    assert payload["start_at"] == "2026-10-25T15:00:00Z"
    assert payload["end_at"] == "2026-10-25T17:00:00Z"
    assert payload["occurred_at"] == "2026-10-23T12:00:00Z"
    assert payload["timezone"] == "America/New_York"
    assert payload["location_name"] == "Main Marina"
    assert payload["staff_names"] == "Jordan Lee"
    assert payload["waiver_required"] is True
    assert payload["waiver_status"] == "unsigned"
    assert payload["waiver_url"].endswith("/waiver/demo-token")
    assert payload["items"][0] == {
        "name": "Adult ticket", "quantity": 2, "amount": "100.00",
        "booking_status": "confirmed", "calendar_id": str(bookings[0].calendar_id),
        "calendar_name": "Sunset Boat Tour", "start_at": "2026-10-25T15:00:00Z",
        "end_at": "2026-10-25T17:00:00Z",
    }
    assert payload["source"] == "passport" and payload["schema_version"] == "1"


def test_pending_card_is_never_presented_as_confirmed():
    db, operator, order, _ = _scenario()
    payload = _payload(db, operator, order)
    _assert_published_shape(payload)
    assert payload["confirmed"] is False
    assert payload["booking_status"] == "pending_payment"
    assert payload["payment_status"] == "requires_payment"
    # No waiver link exists before confirmation, and none is invented.
    assert payload["waiver_status"] == "not_available"
    assert payload["waiver_url"] == ""


def test_invoice_booking_reports_its_pending_invoice():
    db, operator, order, _ = _scenario(method="invoice")
    payload = _payload(db, operator, order)
    assert payload["payment_method"] == "invoice"
    assert payload["payment_status"] == "requires_payment"
    assert payload["confirmed"] is False


def test_free_booking_is_confirmed_at_creation():
    db, operator, order, _ = _scenario(
        method="none", order_status="confirmed", payment_status="succeeded", booking_status="confirmed",
        waiver_status="signed",
    )
    payload = _payload(db, operator, order)
    assert payload["confirmed"] is True
    assert payload["payment_method"] == "none"
    assert payload["waiver_status"] == "signed"


def test_missing_phone_and_no_waiver_use_empty_strings_not_nulls():
    db, operator, order, _ = _scenario(
        phone=None, waiver_text=None, waiver_status="none", staff=(),
        order_status="confirmed", payment_status="succeeded", booking_status="confirmed",
    )
    payload = _payload(db, operator, order)
    _assert_published_shape(payload)
    assert payload["customer_phone"] == ""
    assert payload["waiver_required"] is False
    assert payload["waiver_status"] == "not_required"
    assert payload["waiver_url"] == ""
    assert payload["staff_names"] == ""


def test_multi_booking_order_keeps_every_calendar_in_items():
    db, operator, order, bookings = _scenario(
        second_booking=True, order_status="confirmed", payment_status="succeeded", booking_status="confirmed"
    )
    payload = _payload(db, operator, order)
    assert [item["calendar_name"] for item in payload["items"]] == ["Sunset Boat Tour", "Kayak Rentals"]
    assert payload["items"][1]["start_at"] == "2026-10-25T18:00:00Z"
    assert payload["items"][1]["amount"] == "100.00"  # no line items: falls back to the booking
    assert payload["calendar_id"] == str(bookings[0].calendar_id)  # earliest active booking
    focused = _payload(db, operator, order, "booking_cancelled", focus=bookings[1].id)
    assert focused["calendar_name"] == "Kayak Rentals"
    assert focused["location_name"] == "North Dock"


def test_amounts_and_timestamps_format():
    assert format_amount(0) == "0.00"
    assert format_amount(11_305) == "113.05"
    assert iso_utc(datetime(2026, 10, 25, 11, 0, tzinfo=UTC)) == "2026-10-25T11:00:00Z"
    assert iso_utc(None) == ""


def test_execute_url_must_be_highlevel_trigger_host():
    assert is_execute_url(TARGET)
    for bad in (
        "http://services.leadconnectorhq.com/workflows-marketplace/triggers/execute/abc/def",
        "https://evil.example/workflows-marketplace/triggers/execute/abc",
        "https://services.leadconnectorhq.com.evil.example/workflows-marketplace/triggers/execute/a",
        "https://user:pw@services.leadconnectorhq.com/workflows-marketplace/triggers/execute/a",
        "https://services.leadconnectorhq.com/contacts/",
        "https://services.leadconnectorhq.com/workflows-marketplace/triggers/execute/",
        None,
    ):
        assert not is_execute_url(bad), bad


def test_filters_gate_pending_payments_out_of_a_confirmation_workflow():
    pending = {"event_type": "booking_created", "confirmed": False, "payment_status": "requires_payment"}
    paid = {"event_type": "booking_confirmed", "confirmed": True, "payment_status": "succeeded"}
    confirmation = [{"field": "confirmed", "operator": "==", "value": "true"}]
    assert not matches_filters(confirmation, pending)
    assert matches_filters(confirmation, paid)
    multi = [{"field": "event_type", "operator": "==", "value": ["booking_created", "booking_confirmed"]}]
    assert matches_filters(multi, pending) and matches_filters(multi, paid)
    assert not matches_filters([{"field": "payment_status", "operator": "!=", "value": "succeeded"}], paid)
    # Unknown operators and fields are left to HighLevel.
    assert matches_filters([{"field": "confirmed", "operator": "contains", "value": "x"}], pending)
    assert matches_filters([{"field": "unknown", "operator": "==", "value": "x"}], pending)


def test_errors_never_carry_urls():
    message = redact_error(f"HighLevel request failed (404): {{'url': '{TARGET}'}}")
    assert "leadconnectorhq" not in message and "[url]" in message


def test_disabled_flag_writes_nothing():
    db = MagicMock()
    enqueue_workflow_event(db, Settings(ghl_workflow_trigger_enabled=False), SimpleNamespace(id=uuid.uuid4()), "booking_created", "v1")
    enqueue_workflow_event(
        db, Settings(ghl_workflow_trigger_enabled=True, ghl_sync_mode="disabled"),
        SimpleNamespace(id=uuid.uuid4()), "booking_created", "v1",
    )
    db.assert_not_called()
    assert not db.method_calls


def test_job_type_is_allowed_by_model_and_migration():
    constraint = next(
        c for c in OutboxJob.__table__.constraints
        if "stripe_create_transfer" in str(getattr(c, "sqltext", ""))
    )
    assert "'ghl_workflow_trigger'" in str(constraint.sqltext)
    migration = (ROOT / "supabase" / "migrations" / "045_marketplace_workflow_trigger.sql").read_text()
    assert "'ghl_workflow_trigger'" in migration
    for table in ("ghl_workflow_trigger_subscriptions", "ghl_workflow_trigger_events", "ghl_workflow_trigger_deliveries"):
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in migration
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in migration


def test_booking_created_has_one_producer_shared_by_all_entry_points():
    """Public link, staff link and Passport/PWA bookings all call OrderService.create."""
    app_dir = ROOT / "backend" / "app"
    producers = [
        path.relative_to(app_dir).as_posix()
        for path in app_dir.rglob("*.py")
        if '"booking_created", "v1"' in path.read_text(encoding="utf-8")
    ]
    assert producers == ["services/order_service.py"]
    for route_file in ("api/v1/orders.py", "api/v1/staff_booking.py", "api/v1/bookings.py"):
        assert "OrderService(" in (app_dir / route_file).read_text(encoding="utf-8"), route_file


@pytest.fixture
def client():
    from app.main import app

    app.dependency_overrides[get_db] = lambda: MagicMock()
    yield app
    app.dependency_overrides.clear()


def _callback(app, settings, body, secret="s3cret"):
    app.dependency_overrides[get_settings] = lambda: settings
    headers = {SECRET_HEADER: secret} if secret is not None else {}
    content = body if isinstance(body, str) else json.dumps(body)
    with TestClient(app) as http:
        return http.post(
            "/api/v1/integrations/marketplace/workflow-trigger/subscription",
            content=content,
            headers={"Content-Type": "application/json", **headers},
        )


def _body(**trigger):
    return {
        "triggerData": {"id": "def", "key": "passport_booking_created", "filters": [], "eventType": "CREATED", "targetUrl": TARGET, **trigger},
        "meta": {"key": "passport_booking_created", "version": "1.0"},
        "extras": {"locationId": "ghj", "workflowId": "qwe", "companyId": "asd"},
    }


def test_callback_is_refused_until_a_secret_is_configured(client):
    response = _callback(client, Settings(ghl_workflow_trigger_secret=""), _body())
    assert response.status_code == 503


@pytest.mark.parametrize("secret", [None, "", "wrong"])
def test_callback_rejects_missing_or_wrong_secret(client, secret):
    response = _callback(client, Settings(ghl_workflow_trigger_secret="s3cret"), _body(), secret=secret)
    assert response.status_code == 401
    assert TARGET not in response.text


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        _body(key="some_other_trigger"),
        _body(eventType="PAUSED"),
        _body(targetUrl="https://evil.example/execute"),
        {"triggerData": {"id": "def", "key": "passport_booking_created", "eventType": "CREATED", "targetUrl": TARGET}, "extras": {}},
    ],
)
def test_callback_rejects_malformed_subscriptions_before_touching_storage(client, body):
    response = _callback(client, Settings(ghl_workflow_trigger_secret="s3cret"), body)
    assert response.status_code == 400


# Event Type options of the published v1.0 trigger (its multi-select filter).
PUBLISHED_EVENT_OPTIONS = {
    "booking_created", "booking_confirmed", "payment_updated",
    "waiver_signed", "booking_cancelled", "booking_rescheduled",
}


def test_every_event_passport_sends_is_a_published_filter_option():
    from app.services.ghl_workflow_trigger_service import EVENT_TYPES

    assert EVENT_TYPES <= PUBLISHED_EVENT_OPTIONS
    app_dir = ROOT / "backend" / "app"
    sent = set()
    for path in app_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        # Only the quoted names inside each enqueue_workflow_event(...) call.
        for call in re.finditer(r"enqueue_workflow_event\((.{0,400}?)\)\s*$", text, re.S | re.M):
            sent |= set(re.findall(r'"((?:booking|payment)_[a-z]+)"', call.group(1)))
    assert sent and sent <= PUBLISHED_EVENT_OPTIONS, sent


def test_a_failed_event_write_never_blocks_the_booking():
    from sqlalchemy.exc import ProgrammingError

    db = MagicMock()
    db.scalar.side_effect = ProgrammingError("INSERT", {}, Exception("relation does not exist"))
    order = SimpleNamespace(id=uuid.uuid4(), operator_id=uuid.uuid4())
    import app.services.ghl_workflow_trigger_service as service

    original = service.build_snapshot
    service.build_snapshot = lambda *args, **kwargs: {}
    try:
        enqueue_workflow_event(db, Settings(ghl_workflow_trigger_enabled=True), order, "booking_created", "v1")
    finally:
        service.build_snapshot = original
    db.begin_nested.assert_called_once()
    db.commit.assert_not_called()
    db.rollback.assert_not_called()  # only the savepoint is undone


def test_event_name_migration_keeps_history_and_renames_undelivered():
    migration = (ROOT / "supabase" / "migrations" / "046_trigger_event_type_names.sql").read_text()
    for name in PUBLISHED_EVENT_OPTIONS - {"waiver_signed"} | {"payment_confirmed", "booking_updated"}:
        assert f"'{name}'" in migration
    assert "status <> 'delivered'" in migration
