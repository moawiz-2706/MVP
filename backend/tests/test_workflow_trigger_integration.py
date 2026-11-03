"""Marketplace Custom Trigger against a real Postgres (TEST_DATABASE_URL).

No live HighLevel: the execution call and contact sync are replaced by fakes.
"""

import json
import os
import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.encryption import TokenCipher
from app.core.exceptions import NotFoundError
from app.models.entities import (
    BookingOrder,
    Calendar,
    CalendarHour,
    GHLInstallation,
    GHLWorkflowTriggerDelivery,
    GHLWorkflowTriggerEvent,
    GHLWorkflowTriggerSubscription,
    Operator,
    OutboxJob,
    Payment,
)
from app.schemas.order import OrderCreateRequest, OrderCustomer, OrderItemRequest
from app.services import ghl_client
from app.services.ghl_client import GHLAPIError
from app.services.ghl_workflow_trigger_service import (
    SubscriptionCallbackError,
    WorkflowTriggerDeliveryService,
    WorkflowTriggerRetry,
    WorkflowTriggerStatusService,
    WorkflowTriggerSubscriptionService,
    enqueue_workflow_event,
)
from app.services.order_service import BookingAttribution, OrderService
from app.services.outbox_service import OutboxService

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)

KEY = "test-token-encryption-key"
SETTINGS = Settings(
    ghl_notifications_enabled=False,
    ghl_sync_mode="outbox",
    ghl_workflow_trigger_enabled=True,
    ghl_workflow_trigger_secret="s3cret",
    ghl_token_encryption_key=KEY,
)
TARGET = "https://services.leadconnectorhq.com/workflows-marketplace/triggers/execute/app/{}"


class FakeExecute:
    """Stands in for GHLClient: records trigger posts, answers per target URL."""

    posts: list[tuple[str, dict]] = []
    responses: dict[str, Exception] = {}

    def __init__(self, operator_id, db=None) -> None:
        self.operator_id = operator_id

    def post_workflow_trigger(self, target_url, payload):
        FakeExecute.posts.append((target_url, payload))
        error = FakeExecute.responses.get(target_url)
        if error is not None:
            raise error
        return {}


@pytest.fixture()
def execute(monkeypatch, ghl):
    FakeExecute.posts, FakeExecute.responses = [], {}
    monkeypatch.setattr(ghl_client, "GHLClient", FakeExecute)
    return FakeExecute


def _shop(db, *, location=None):
    operator = Operator(
        ghl_location_id=location or f"loc-{uuid.uuid4().hex}", name="Op",
        slug=f"op-{uuid.uuid4().hex[:8]}", time_zone="America/New_York", public_booking_enabled=True,
    )
    db.add(operator)
    db.flush()
    db.add(
        GHLInstallation(
            operator_id=operator.id, location_id=operator.ghl_location_id,
            access_token_encrypted="x", refresh_token_encrypted="x",
            access_token_expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    calendar = Calendar(
        operator_id=operator.id, name="Sunset Boat Tour", slug=f"t-{uuid.uuid4().hex[:8]}",
        duration_minutes=120, slot_interval_minutes=60, base_price_minor=5000, public_booking_enabled=True,
    )
    db.add(calendar)
    db.flush()
    db.add_all([CalendarHour(calendar_id=calendar.id, day_of_week=d, start_time=time(0), end_time=time(23, 59)) for d in range(7)])
    db.commit()
    return operator, calendar


def _book(db, operator, calendar, *, hour=15, source=None):
    request = OrderCreateRequest(
        items=[OrderItemRequest(calendar_id=calendar.id, start_at=datetime(2027, 1, 4, hour, tzinfo=UTC), units=2)],
        customer=OrderCustomer(first_name="Alex", last_name="Smith", email="alex@example.com"),
        payment_required=False,
    )
    result = OrderService(db, SETTINGS).create(
        operator.slug, request, allow_payment_override=True,
        attribution=BookingAttribution(source=source) if source else None,
    )
    return db.scalar(select(BookingOrder).where(BookingOrder.public_reference == result.public_reference))


def _subscribe(db, operator, workflow="wf-1", event="CREATED", trigger_id=None, filters=None):
    body = {
        "triggerData": {
            "id": trigger_id or f"trg-{workflow}", "key": "passport_booking_created",
            "filters": filters or [], "eventType": event, "targetUrl": TARGET.format(workflow),
        },
        "meta": {"key": "passport_booking_created", "version": "1.0"},
        "extras": {"locationId": operator.ghl_location_id, "workflowId": workflow, "companyId": "co"},
    }
    raw = json.dumps(body).encode()
    return WorkflowTriggerSubscriptionService(db, SETTINGS).handle(body, raw)


def _events(db, order):
    return list(db.scalars(select(GHLWorkflowTriggerEvent).where(GHLWorkflowTriggerEvent.booking_order_id == order.id)))


def test_subscription_lifecycle_is_encrypted_idempotent_and_final_on_delete(db):
    operator, _ = _shop(db)
    assert _subscribe(db, operator) == {"success": True}
    assert _subscribe(db, operator) == {"success": True, "duplicate": True}
    row = db.scalar(select(GHLWorkflowTriggerSubscription))
    assert TARGET.format("wf-1") not in row.target_url_encrypted
    assert TokenCipher(KEY).decrypt(row.target_url_encrypted) == TARGET.format("wf-1")

    _subscribe(db, operator, event="UPDATED", filters=[{"field": "confirmed", "operator": "==", "value": "true"}])
    db.refresh(row)
    assert row.status == "active" and row.filters[0]["field"] == "confirmed"

    _subscribe(db, operator, event="DELETED")
    db.refresh(row)
    assert row.status == "deleted"
    # A replayed CREATED must not resurrect a removed workflow.
    assert _subscribe(db, operator, event="CREATED", filters=[{"replay": True}])["ignored"] is True
    db.refresh(row)
    assert row.status == "deleted"
    assert db.scalar(select(func.count()).select_from(GHLWorkflowTriggerSubscription)) == 1


def test_unknown_or_uninstalled_location_never_stores_a_target(db):
    operator, _ = _shop(db)
    stranger = Operator(ghl_location_id="loc-unknown", name="X", slug="x-unknown", time_zone="UTC")
    with pytest.raises(SubscriptionCallbackError) as exc:
        _subscribe(db, stranger)
    assert exc.value.status_code == 403
    installation = db.scalar(select(GHLInstallation).where(GHLInstallation.operator_id == operator.id))
    installation.lifecycle_status = "uninstalled"
    db.commit()
    with pytest.raises(SubscriptionCallbackError):
        _subscribe(db, operator)
    db.rollback()
    assert db.scalar(select(func.count()).select_from(GHLWorkflowTriggerSubscription)) == 0


@pytest.mark.parametrize("source", [None, "staff_link", "pwa"])
def test_each_entry_point_records_exactly_one_booking_created_event(db, source):
    operator, calendar = _shop(db)
    order = _book(db, operator, calendar, source=source)
    events = _events(db, order)
    assert [event.event_type for event in events] == ["booking_created"]
    assert events[0].snapshot["confirmed"] is True  # free booking
    jobs = db.scalar(
        select(func.count()).select_from(OutboxJob).where(
            OutboxJob.booking_order_id == order.id, OutboxJob.job_type == "ghl_workflow_trigger"
        )
    )
    assert jobs == 1
    # A repeated call (request retry, webhook redelivery) is a no-op.
    enqueue_workflow_event(db, SETTINGS, order, "booking_created", "v1")
    db.commit()
    assert len(_events(db, order)) == 1


def test_pending_card_then_booking_confirmed_are_two_distinct_events(db):
    operator, calendar = _shop(db)
    order = _book(db, operator, calendar)
    payment = db.scalar(select(Payment).where(Payment.booking_order_id == order.id))
    created = _events(db, order)[0]
    # Simulate a card hold being created instead of a free booking.
    created.snapshot = {**created.snapshot, "booking_status": "pending_payment",
                        "payment_status": "requires_payment", "confirmed": False}
    db.commit()
    enqueue_workflow_event(db, SETTINGS, order, "booking_confirmed", "v1")
    enqueue_workflow_event(db, SETTINGS, order, "booking_confirmed", "v1")  # Stripe redelivery
    db.commit()
    by_type = {event.event_type: event for event in _events(db, order)}
    assert set(by_type) == {"booking_created", "booking_confirmed"}
    assert by_type["booking_created"].snapshot["confirmed"] is False
    assert by_type["booking_confirmed"].snapshot["confirmed"] is True
    assert payment.status == "succeeded"


def test_delivery_to_multiple_workflows_retries_only_the_failed_one(db, execute):
    operator, calendar = _shop(db)
    _subscribe(db, operator, "wf-1")
    _subscribe(db, operator, "wf-2")
    order = _book(db, operator, calendar)
    event = _events(db, order)[0]
    execute.responses[TARGET.format("wf-2")] = GHLAPIError("HighLevel request failed (503)", status_code=503)

    service = WorkflowTriggerDeliveryService(db, operator.id, SETTINGS)
    with pytest.raises(WorkflowTriggerRetry):
        service.deliver(event.id)
    db.refresh(event)
    assert event.status == "partially_delivered"
    assert [url for url, _ in execute.posts] == [TARGET.format("wf-1"), TARGET.format("wf-2")]
    # The contact was created by the existing contact sync before sending.
    assert execute.posts[0][1]["ghl_contact_id"]

    execute.responses.clear()
    execute.posts.clear()
    service.deliver(event.id)
    db.refresh(event)
    assert event.status == "delivered"
    assert [url for url, _ in execute.posts] == [TARGET.format("wf-2")]
    service.deliver(event.id)  # a duplicate run sends nothing
    assert len(execute.posts) == 1


def test_permanent_rejection_stops_and_manual_retry_resends_once(db, execute):
    operator, calendar = _shop(db)
    _subscribe(db, operator, "wf-1")
    order = _book(db, operator, calendar)
    event = _events(db, order)[0]
    execute.responses[TARGET.format("wf-1")] = GHLAPIError("HighLevel request failed (422)", status_code=422)
    WorkflowTriggerDeliveryService(db, operator.id, SETTINGS).deliver(event.id)
    db.refresh(event)
    delivery = db.scalar(select(GHLWorkflowTriggerDelivery).where(GHLWorkflowTriggerDelivery.event_id == event.id))
    assert (event.status, delivery.status, delivery.last_http_status) == ("failed", "failed", 422)
    assert "leadconnectorhq" not in (delivery.last_error or "")

    execute.responses.clear()
    status = WorkflowTriggerStatusService(db, operator.id)
    assert status.retry(order.id) == 1
    OutboxService(db, SETTINGS).process(limit=50, prefer_newest=True)
    db.refresh(event)
    assert event.status == "delivered"
    assert status.retry(order.id) == 0  # delivered events are never resent


def test_no_subscriber_is_recorded_not_reported_as_delivered(db, execute):
    operator, calendar = _shop(db)
    order = _book(db, operator, calendar)
    event = _events(db, order)[0]
    WorkflowTriggerDeliveryService(db, operator.id, SETTINGS).deliver(event.id)
    db.refresh(event)
    assert event.status == "no_subscriber" and event.delivered_at is None
    assert execute.posts == []


def test_workflow_filters_keep_unconfirmed_events_out(db, execute):
    operator, calendar = _shop(db)
    _subscribe(db, operator, "wf-1", filters=[{"field": "payment_status", "operator": "==", "value": "requires_payment"}])
    order = _book(db, operator, calendar)  # free: payment succeeded
    event = _events(db, order)[0]
    WorkflowTriggerDeliveryService(db, operator.id, SETTINGS).deliver(event.id)
    db.refresh(event)
    assert event.status == "no_subscriber" and execute.posts == []


def test_status_and_retry_are_tenant_isolated(db):
    operator, calendar = _shop(db)
    other, _ = _shop(db)
    order = _book(db, operator, calendar)
    assert WorkflowTriggerStatusService(db, operator.id).order_status(order.id)["events"]
    with pytest.raises(NotFoundError):
        WorkflowTriggerStatusService(db, other.id).order_status(order.id)
    with pytest.raises(NotFoundError):
        WorkflowTriggerStatusService(db, other.id).retry(order.id)


def test_dead_outbox_job_marks_the_event_failed(db, execute):
    operator, calendar = _shop(db)
    _subscribe(db, operator, "wf-1")
    order = _book(db, operator, calendar)
    execute.responses[TARGET.format("wf-1")] = GHLAPIError("HighLevel request failed (500)", status_code=500)
    job = db.scalar(select(OutboxJob).where(OutboxJob.job_type == "ghl_workflow_trigger", OutboxJob.booking_order_id == order.id))
    other_jobs = db.scalars(select(OutboxJob).where(OutboxJob.id != job.id))
    for other in other_jobs:
        other.status = "completed"
    db.commit()
    settings = SETTINGS.model_copy(update={"outbox_max_attempts": 1})
    OutboxService(db, settings).process(limit=10)
    db.refresh(job)
    event = _events(db, order)[0]
    assert job.status == "dead"
    assert event.status == "failed"

