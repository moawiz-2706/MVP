"""HighLevel Marketplace Workflow Custom Trigger `passport_booking_created`.

Three parts, kept separate from the ordinary contact/appointment projection:

* Subscriptions: HighLevel calls the Subscription URL when a workflow adds,
  changes or removes the trigger. Each workflow trigger instance is one row;
  its execution targetUrl is encrypted and never leaves the backend.
* Events: booking code calls `enqueue_workflow_event` inside the same
  transaction as the booking change. One row per logical event, unique by a
  deterministic idempotency key, plus one durable outbox job.
* Delivery: the outbox job posts the payload to every active subscription for
  the booking's location, recording one delivery row per workflow.

The trigger only starts workflows. It never creates contacts or appointments
itself; when the booking has no HighLevel contact yet, the existing contact
sync runs first so `ghl_contact_id` is always real.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.encryption import TokenCipher
from app.core.exceptions import NotFoundError
from app.services.partner_service import partner_split
from app.models.entities import (
    Booking,
    Calendar,
    CalendarCategory,
    BookingLineItem,
    BookingOrder,
    GHLInstallation,
    GHLWorkflowTriggerDelivery,
    GHLWorkflowTriggerEvent,
    GHLWorkflowTriggerSubscription,
    Operator,
    OutboxJob,
    Payment,
    Staff,
    StaffAssignment,
)

TRIGGER_KEY = "passport_booking_created"
SCHEMA_VERSION = "1"
SOURCE = "passport"
SECRET_HEADER = "X-Passport-Trigger-Secret"
EXECUTE_HOST = "services.leadconnectorhq.com"
EXECUTE_PATH_PREFIX = "/workflows-marketplace/triggers/execute/"
# The values offered by the published v1.0 trigger's Event Type filter, so a
# workflow filtered on them starts for every event Passport sends.
EVENT_TYPES = {
    "booking_created",
    "booking_confirmed",
    "booking_rescheduled",
    "payment_updated",
    "booking_cancelled",
}
CALLBACK_EVENTS = {"CREATED", "UPDATED", "DELETED"}
RETRYABLE_STATUSES = {408, 409, 425, 429}
logger = logging.getLogger("passport.workflow_trigger")
INACTIVE_BOOKING_STATUSES = {"cancelled", "failed", "expired"}
_URL_PATTERN = re.compile(r"https?://\S+")
PARTNER_FIELDS: dict[str, Any] = {
    "source_partner": "Direct",
    "gross_booking_amount": "0.00",
    "hotel_commission_20pct": "0.00",
    "pga_commission_30pct": "0.00",
    "net_to_operator": "0.00",
    "gratuity_amount": "0.00",
    "number_of_guests": 0,
    "tour_date": "",
    "tour_type": "",
    "tour_start_local": "",
    "tour_end_local": "",
}


class SubscriptionCallbackError(ValueError):
    def __init__(self, message: str, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(message)


class WorkflowTriggerRetry(RuntimeError):
    """At least one workflow failed transiently; the outbox job retries it."""


def iso_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_amount(amount_minor: int | None) -> str:
    return f"{Decimal(int(amount_minor or 0)) / Decimal(100):.2f}"


def redact_error(message: str) -> str:
    """Error text safe to store and show: no URLs (a targetUrl is a secret)."""
    return _URL_PATTERN.sub("[url]", message)[:500]


def is_execute_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == EXECUTE_HOST
        and parsed.port in {None, 443}
        and not parsed.username
        and not parsed.password
        and parsed.path.startswith(EXECUTE_PATH_PREFIX)
        and len(parsed.path) > len(EXECUTE_PATH_PREFIX)
    )


class WorkflowTriggerSubscriptionService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def verify_secret(self, supplied: str | None) -> None:
        expected = self.settings.ghl_workflow_trigger_secret
        if not expected:
            raise SubscriptionCallbackError("Workflow trigger subscriptions are not configured", 503)
        if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise SubscriptionCallbackError("Invalid workflow trigger subscription credentials", 401)

    def handle(self, payload: object, raw_body: bytes) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise SubscriptionCallbackError("Invalid subscription payload", 400)
        trigger = payload.get("triggerData")
        extras = payload.get("extras")
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        if not isinstance(trigger, dict) or not isinstance(extras, dict):
            raise SubscriptionCallbackError("Invalid subscription payload", 400)
        key = trigger.get("key") or meta.get("key")
        if key != TRIGGER_KEY or (meta.get("key") not in {None, TRIGGER_KEY}):
            raise SubscriptionCallbackError("Unknown trigger key", 400)
        event = str(trigger.get("eventType") or "").upper()
        if event not in CALLBACK_EVENTS:
            raise SubscriptionCallbackError("Unknown subscription event type", 400)
        trigger_id = trigger.get("id")
        location_id = extras.get("locationId")
        workflow_id = extras.get("workflowId")
        if not all(isinstance(value, str) and value for value in (trigger_id, location_id, workflow_id)):
            raise SubscriptionCallbackError("Subscription is missing its trigger, location or workflow", 400)
        filters = trigger.get("filters") or []
        if not isinstance(filters, list):
            raise SubscriptionCallbackError("Invalid subscription filters", 400)
        target_url = trigger.get("targetUrl")
        if event != "DELETED" and not is_execute_url(target_url):
            raise SubscriptionCallbackError("Subscription targetUrl is not a HighLevel trigger URL", 400)

        installation = self.db.scalar(
            select(GHLInstallation).where(GHLInstallation.location_id == location_id)
        )
        if (
            installation is None
            or not installation.is_installed
            or installation.lifecycle_status != "active"
        ):
            # Never store a target for a location Passport does not serve.
            raise SubscriptionCallbackError("Location is not connected to Passport", 403)

        digest = hashlib.sha256(raw_body).hexdigest()
        now = datetime.now(UTC)
        existing = self._locked(location_id, workflow_id, trigger_id)
        if existing is not None and existing.last_callback_hash == digest:
            self.db.rollback()
            return {"success": True, "duplicate": True}
        if existing is not None and existing.status == "deleted" and event != "DELETED":
            # Removal is final for a trigger instance; a replayed older
            # CREATED/UPDATED must not resurrect a workflow the user removed.
            self.db.rollback()
            return {"success": True, "ignored": True}
        if event == "DELETED":
            if existing is not None:
                existing.status = "deleted"
                existing.deleted_at = now
                existing.last_callback_event = event
                existing.last_callback_hash = digest
                existing.last_callback_at = now
            self.db.commit()
            return {"success": True}

        encrypted = TokenCipher(self.settings.ghl_token_encryption_key).encrypt(str(target_url))
        version = str(meta.get("version")) if meta.get("version") is not None else None
        company_id = extras.get("companyId") if isinstance(extras.get("companyId"), str) else None
        if existing is None:
            self.db.execute(
                insert(GHLWorkflowTriggerSubscription)
                .values(
                    operator_id=installation.operator_id,
                    ghl_location_id=location_id,
                    ghl_company_id=company_id,
                    ghl_workflow_id=workflow_id,
                    ghl_trigger_id=trigger_id,
                    trigger_key=TRIGGER_KEY,
                    trigger_version=version,
                    target_url_encrypted=encrypted,
                    filters=filters,
                    status="active",
                    last_callback_event=event,
                    last_callback_hash=digest,
                    last_callback_at=now,
                )
                .on_conflict_do_nothing(constraint="uq_ghl_workflow_trigger_subscription")
            )
            existing = self._locked(location_id, workflow_id, trigger_id)
            if existing is None:
                raise RuntimeError("Unable to store workflow trigger subscription")
            if existing.last_callback_hash == digest:
                self.db.commit()
                return {"success": True}
        existing.operator_id = installation.operator_id
        existing.ghl_company_id = company_id
        existing.trigger_version = version
        existing.target_url_encrypted = encrypted
        existing.filters = filters
        existing.last_callback_event = event
        existing.last_callback_hash = digest
        existing.last_callback_at = now
        self.db.commit()
        return {"success": True}

    def _locked(
        self, location_id: str, workflow_id: str, trigger_id: str
    ) -> GHLWorkflowTriggerSubscription | None:
        return self.db.scalar(
            select(GHLWorkflowTriggerSubscription)
            .where(
                GHLWorkflowTriggerSubscription.ghl_location_id == location_id,
                GHLWorkflowTriggerSubscription.ghl_workflow_id == workflow_id,
                GHLWorkflowTriggerSubscription.ghl_trigger_id == trigger_id,
            )
            .with_for_update()
        )


def _order_bookings(db: Session, order: BookingOrder) -> list[Booking]:
    return list(
        db.scalars(
            select(Booking)
            .where(Booking.booking_order_id == order.id, Booking.operator_id == order.operator_id)
            .order_by(Booking.start_at, Booking.id)
        )
    )


def _primary_booking(bookings: list[Booking], focus_booking_id: uuid.UUID | None) -> Booking | None:
    if focus_booking_id is not None:
        for booking in bookings:
            if booking.id == focus_booking_id:
                return booking
    active = [booking for booking in bookings if booking.status not in INACTIVE_BOOKING_STATUSES]
    return (active or bookings or [None])[0]


def build_snapshot(
    db: Session, order: BookingOrder, *, focus_booking_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """Booking, payment and item fields as they stand in this transaction.

    One event per order. The top-level calendar fields describe the primary
    booking (the one changed, else the earliest active one); `items` lists
    every line of every booking in the order with its own calendar and times,
    so a multi-calendar checkout is never flattened or dropped.
    """
    operator = db.get(Operator, order.operator_id)
    payment = db.scalar(select(Payment).where(Payment.booking_order_id == order.id))
    bookings = _order_bookings(db, order)
    primary = _primary_booking(bookings, focus_booking_id)
    lines: dict[uuid.UUID, list[BookingLineItem]] = {}
    if bookings:
        for line in db.scalars(
            select(BookingLineItem)
            .where(BookingLineItem.booking_id.in_([booking.id for booking in bookings]))
            .order_by(BookingLineItem.created_at, BookingLineItem.id)
        ):
            lines.setdefault(line.booking_id, []).append(line)
    items: list[dict[str, Any]] = []
    for booking in bookings:
        common = {
            "booking_id": str(booking.id),
            "booking_status": booking.status,
            "calendar_id": str(booking.calendar_id),
            "calendar_name": booking.calendar_name_snapshot,
            "start_at": iso_utc(booking.start_at),
            "end_at": iso_utc(booking.end_at),
        }
        booking_lines = lines.get(booking.id) or []
        if booking_lines:
            for line in booking_lines:
                items.append(
                    {
                        "name": line.customer_type_name_snapshot,
                        "quantity": line.quantity,
                        "amount": format_amount(line.line_subtotal_minor),
                        **common,
                    }
                )
        else:
            items.append(
                {
                    "name": booking.customer_type_name_snapshot or booking.calendar_name_snapshot,
                    "quantity": booking.units,
                    "amount": format_amount(
                        booking.line_subtotal_minor or booking.base_price_minor * booking.units
                    ),
                    **common,
                }
            )
    payment_status = payment.status if payment else "unknown"
    split = partner_split(order, payment)
    tour_type = ""
    tour_date = ""
    tour_start_local = ""
    tour_end_local = ""
    if primary is not None:
        tour_type = db.scalar(
            select(CalendarCategory.name)
            .join(Calendar, Calendar.calendar_category_id == CalendarCategory.id)
            .where(Calendar.id == primary.calendar_id)
        ) or ""
        try:
            zone = ZoneInfo(operator.time_zone) if operator and operator.time_zone else UTC
        except ZoneInfoNotFoundError:
            zone = UTC
        tour_date = primary.start_at.astimezone(zone).date().isoformat()
        # Ready to print in customer messages, in the operator's time zone,
        # e.g. "Wednesday, December 9, 2026 at 5:15 PM" and "7:15 PM".
        local_start = primary.start_at.astimezone(zone)
        local_end = primary.end_at.astimezone(zone)
        tour_start_local = (
            f"{local_start:%A, %B} {local_start.day}, {local_start.year} at "
            f"{local_start.hour % 12 or 12}:{local_start:%M %p}"
        )
        tour_end_local = f"{local_end.hour % 12 or 12}:{local_end:%M %p}"
    first = order.customer_first_name or ""
    last = order.customer_last_name or ""
    return {
        "booking_order_id": str(order.id),
        "public_reference": order.public_reference,
        "booking_status": order.status,
        "payment_status": payment_status,
        "payment_method": payment.payment_method if payment else "none",
        "confirmed": order.status == "confirmed" and payment_status == "succeeded",
        "currency": (order.currency or "").upper(),
        "subtotal_amount": format_amount(order.subtotal_minor),
        "fees_and_taxes_amount": format_amount(order.platform_fee_and_taxes_minor),
        "customer_total_amount": format_amount(order.customer_total_minor),
        "customer_first_name": first,
        "customer_last_name": last,
        "customer_full_name": f"{first} {last}".strip(),
        "customer_email": order.customer_email or "",
        "customer_phone": order.customer_phone or "",
        "calendar_name": primary.calendar_name_snapshot if primary else "",
        "calendar_id": str(primary.calendar_id) if primary else "",
        "primary_booking_id": str(primary.id) if primary else "",
        "start_at": iso_utc(primary.start_at) if primary else "",
        "end_at": iso_utc(primary.end_at) if primary else "",
        "timezone": operator.time_zone if operator else "",
        "location_name": (primary.departure_location_name_snapshot or "") if primary else "",
        "items": items,
        # Hotel-partner fields (the Opportunity fields of the partner scope).
        "source_partner": split.source_partner,
        "gross_booking_amount": format_amount(split.gross_minor),
        "hotel_commission_20pct": format_amount(split.hotel_commission_minor),
        "pga_commission_30pct": format_amount(split.pga_commission_minor),
        "net_to_operator": format_amount(split.net_to_operator_minor),
        "gratuity_amount": format_amount(split.gratuity_minor),
        "number_of_guests": sum(
            booking.units for booking in bookings if booking.status not in {"failed", "expired"}
        ),
        "tour_date": tour_date,
        "tour_type": tour_type,
        "tour_start_local": tour_start_local,
        "tour_end_local": tour_end_local,
    }


def enqueue_workflow_event(
    db: Session,
    settings: Settings,
    order: BookingOrder,
    event_type: str,
    discriminator: str,
    *,
    focus_booking_id: uuid.UUID | None = None,
) -> None:
    """Record one logical trigger event and its outbox job in the caller's transaction.

    The caller commits; nothing is sent until then. A repeated call with the
    same (order, event_type, discriminator) is a no-op, so webhook redelivery
    and request retries never create a second event.

    The writes run in a savepoint: if they fail (for example a migration not
    yet applied), only the trigger event is lost and logged. The booking or
    payment the caller is saving always goes ahead.

    Every booking change passes through here, so it also refreshes the
    order's HighLevel "Passport Booking" record (its own flag).
    """
    from app.services.ghl_booking_record_service import enqueue_booking_record_sync

    enqueue_booking_record_sync(db, settings, order)
    if not settings.ghl_workflow_trigger_enabled or settings.ghl_sync_mode == "disabled":
        return
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unsupported workflow trigger event: {event_type}")
    db.flush()
    idempotency_key = f"booking_order:{order.id}:workflow:{event_type}:{discriminator}"
    try:
        with db.begin_nested():
            event_row_id = db.scalar(
                insert(GHLWorkflowTriggerEvent)
                .values(
                    operator_id=order.operator_id,
                    booking_order_id=order.id,
                    event_type=event_type,
                    event_id=f"{order.id}:{event_type}:{discriminator}",
                    idempotency_key=idempotency_key,
                    occurred_at=datetime.now(UTC),
                    snapshot=build_snapshot(db, order, focus_booking_id=focus_booking_id),
                    status="pending",
                )
                .on_conflict_do_nothing(constraint="uq_ghl_workflow_trigger_events_idempotency_key")
                .returning(GHLWorkflowTriggerEvent.id)
            )
            if event_row_id is None:
                return
            db.execute(
                insert(OutboxJob)
                .values(
                    operator_id=order.operator_id,
                    booking_order_id=order.id,
                    job_type="ghl_workflow_trigger",
                    idempotency_key=f"workflow_trigger_event:{event_row_id}",
                    payload={"trigger_event_id": str(event_row_id)},
                    status="pending",
                )
                .on_conflict_do_nothing(index_elements=[OutboxJob.idempotency_key])
            )
    except SQLAlchemyError:
        logger.exception(
            "Could not record Marketplace trigger event %s; the booking change is kept",
            idempotency_key,
        )


def _filter_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().lower()


def matches_filters(filters: list[Any], payload: dict[str, Any]) -> bool:
    """Apply the workflow's saved equality filters before sending.

    HighLevel's docs do not say whether it evaluates trigger filters itself, so
    Passport applies `==` / `!=` on its own fields too (re-applying an equality
    filter is harmless). Anything it does not understand is left to HighLevel.
    """
    for item in filters:
        if not isinstance(item, dict):
            continue
        field = item.get("field") or item.get("id")
        operator = item.get("operator")
        if field not in payload or operator not in {"==", "!="} or "value" not in item:
            continue
        actual = payload[field]
        if isinstance(actual, (list, dict)):
            continue
        wanted = item["value"]
        options = wanted if isinstance(wanted, list) else [wanted]
        if not options:
            continue
        hit = _filter_value(actual) in {_filter_value(option) for option in options}
        if (operator == "==" and not hit) or (operator == "!=" and hit):
            return False
    return True


class WorkflowTriggerDeliveryService:
    def __init__(self, db: Session, operator_id: uuid.UUID, settings: Settings) -> None:
        self.db = db
        self.operator_id = operator_id
        self.settings = settings

    def build_payload(self, event: GHLWorkflowTriggerEvent, order: BookingOrder) -> dict[str, Any]:
        from app.services.waiver_service import WaiverService

        snapshot = event.snapshot or {}
        operator = self.db.get(Operator, self.operator_id)
        bookings = _order_bookings(self.db, order)
        primary_id = snapshot.get("primary_booking_id")
        primary = _primary_booking(bookings, uuid.UUID(primary_id) if primary_id else None)
        waiver_service = WaiverService(self.db)
        waiver_required = waiver_service.configured(self.operator_id)
        waiver_status, waiver_link = "not_required", ""
        if waiver_required and primary is not None:
            summary = waiver_service.summary(primary)
            status = summary.get("status")
            if status == "signed":
                waiver_status, waiver_link = "signed", str(summary.get("url") or "")
            elif status == "pending":
                waiver_status, waiver_link = "unsigned", str(summary.get("url") or "")
            else:
                # Pending payment or cancelled: the link is issued only once
                # the booking is confirmed, so none is invented here.
                waiver_status = "not_available"
        staff_names = ""
        if primary is not None:
            names = self.db.scalars(
                select(Staff.name)
                .join(StaffAssignment, StaffAssignment.staff_id == Staff.id)
                .where(
                    StaffAssignment.operator_id == self.operator_id,
                    StaffAssignment.calendar_id == primary.calendar_id,
                    StaffAssignment.start_at == primary.start_at,
                )
                .order_by(Staff.name)
            )
            staff_names = ", ".join(dict.fromkeys(names))
        return {
            "event_type": event.event_type,
            "schema_version": SCHEMA_VERSION,
            "event_id": event.event_id,
            "idempotency_key": event.idempotency_key,
            "occurred_at": iso_utc(event.occurred_at),
            "source": SOURCE,
            "location_id": operator.ghl_location_id if operator else "",
            "booking_order_id": snapshot.get("booking_order_id", str(order.id)),
            "public_reference": snapshot.get("public_reference", order.public_reference),
            "booking_status": snapshot.get("booking_status", ""),
            "payment_status": snapshot.get("payment_status", ""),
            "payment_method": snapshot.get("payment_method", ""),
            "confirmed": bool(snapshot.get("confirmed", False)),
            "currency": snapshot.get("currency", ""),
            "subtotal_amount": snapshot.get("subtotal_amount", "0.00"),
            "fees_and_taxes_amount": snapshot.get("fees_and_taxes_amount", "0.00"),
            "customer_total_amount": snapshot.get("customer_total_amount", "0.00"),
            "customer_first_name": snapshot.get("customer_first_name", ""),
            "customer_last_name": snapshot.get("customer_last_name", ""),
            "customer_full_name": snapshot.get("customer_full_name", ""),
            "customer_email": snapshot.get("customer_email", ""),
            "customer_phone": snapshot.get("customer_phone", ""),
            "ghl_contact_id": order.ghl_contact_id or "",
            "calendar_name": snapshot.get("calendar_name", ""),
            "calendar_id": snapshot.get("calendar_id", ""),
            "start_at": snapshot.get("start_at", ""),
            "end_at": snapshot.get("end_at", ""),
            "timezone": snapshot.get("timezone", ""),
            "location_name": snapshot.get("location_name", ""),
            "waiver_required": waiver_required,
            "waiver_status": waiver_status,
            "waiver_url": waiver_link,
            "staff_names": staff_names,
            "items": [
                {key: value for key, value in item.items() if key != "booking_id"}
                for item in snapshot.get("items", [])
            ],
            # Added after v1.0's variables: usable once a trigger version
            # publishes them as custom variables; ignored by older ones.
            **{key: snapshot.get(key, default) for key, default in PARTNER_FIELDS.items()},
        }

    def deliver(self, trigger_event_id: uuid.UUID) -> None:
        from app.services.ghl_client import GHLAPIError, GHLClient
        from app.services.ghl_contact_service import GHLContactService

        event = self.db.scalar(
            select(GHLWorkflowTriggerEvent).where(
                GHLWorkflowTriggerEvent.id == trigger_event_id,
                GHLWorkflowTriggerEvent.operator_id == self.operator_id,
            )
        )
        if event is None:
            raise RuntimeError("Workflow trigger event not found")
        order = self.db.get(BookingOrder, event.booking_order_id)
        operator = self.db.get(Operator, self.operator_id)
        if order is None or operator is None or order.operator_id != self.operator_id:
            raise RuntimeError("Workflow trigger booking not found")
        subscriptions = list(
            self.db.scalars(
                select(GHLWorkflowTriggerSubscription)
                .where(
                    GHLWorkflowTriggerSubscription.operator_id == self.operator_id,
                    GHLWorkflowTriggerSubscription.ghl_location_id == operator.ghl_location_id,
                    GHLWorkflowTriggerSubscription.trigger_key == TRIGGER_KEY,
                    GHLWorkflowTriggerSubscription.status == "active",
                )
                .order_by(GHLWorkflowTriggerSubscription.created_at)
            )
        )
        if not subscriptions:
            if event.status != "delivered":
                event.status = "no_subscriber"
                event.last_error = "No active workflow uses this trigger in HighLevel"
            self.db.commit()
            return
        if not order.ghl_contact_id:
            # The workflow references the contact, so the existing contact
            # sync (the owner of HighLevel contacts) runs first. It commits.
            GHLContactService(self.db, self.operator_id).sync(order.id)
            self.db.refresh(order)
        payload = self.build_payload(event, order)
        self.db.commit()
        cipher = TokenCipher(self.settings.ghl_token_encryption_key)
        client = GHLClient(self.operator_id, self.db)
        retry = False
        for subscription in subscriptions:
            self.db.execute(
                insert(GHLWorkflowTriggerDelivery)
                .values(
                    operator_id=self.operator_id,
                    event_id=event.id,
                    subscription_id=subscription.id,
                    status="pending",
                )
                .on_conflict_do_nothing(constraint="uq_ghl_workflow_trigger_delivery")
            )
            delivery = self.db.scalar(
                select(GHLWorkflowTriggerDelivery).where(
                    GHLWorkflowTriggerDelivery.event_id == event.id,
                    GHLWorkflowTriggerDelivery.subscription_id == subscription.id,
                )
            )
            if delivery is None or delivery.status in {"delivered", "filtered", "failed"}:
                self.db.commit()
                continue
            if not matches_filters(subscription.filters or [], payload):
                delivery.status = "filtered"
                delivery.last_error = None
                self.db.commit()
                continue
            delivery.attempt_count += 1
            delivery.last_attempt_at = datetime.now(UTC)
            try:
                target_url = cipher.decrypt(subscription.target_url_encrypted)
            except ValueError:
                delivery.status = "failed"
                delivery.last_error = "Stored workflow target could not be decrypted; re-save the workflow in HighLevel"
                self.db.commit()
                continue
            try:
                client.post_workflow_trigger(target_url, payload)
            except GHLAPIError as exc:
                status_code = exc.status_code
                transient = not exc.permanent and (
                    status_code is None or status_code in RETRYABLE_STATUSES or status_code >= 500
                )
                delivery.status = "retrying" if transient else "failed"
                delivery.last_http_status = status_code
                delivery.last_error = redact_error(str(exc))
                retry = retry or transient
            except Exception as exc:  # network and unexpected client errors retry
                delivery.status = "retrying"
                delivery.last_error = redact_error(f"{type(exc).__name__}: {exc}")
                retry = True
            else:
                delivery.status = "delivered"
                delivery.last_http_status = 200
                delivery.last_error = None
                delivery.delivered_at = datetime.now(UTC)
            self.db.commit()
        self._settle(event)
        if retry:
            raise WorkflowTriggerRetry("HighLevel workflow trigger delivery will be retried")

    def _settle(self, event: GHLWorkflowTriggerEvent) -> None:
        statuses = [
            status
            for status in self.db.scalars(
                select(GHLWorkflowTriggerDelivery.status).where(
                    GHLWorkflowTriggerDelivery.event_id == event.id
                )
            )
        ]
        delivered = statuses.count("delivered")
        failed = statuses.count("failed")
        retrying = statuses.count("retrying")
        if retrying:
            event.status = "partially_delivered" if delivered else "pending"
            event.last_error = "Delivery to a workflow failed; it will be retried"
        elif failed:
            event.status = "partially_delivered" if delivered else "failed"
            event.last_error = "HighLevel rejected the trigger for at least one workflow"
        elif delivered:
            event.status = "delivered"
            event.last_error = None
            event.delivered_at = event.delivered_at or datetime.now(UTC)
        else:
            event.status = "no_subscriber"
            event.last_error = "Every subscribed workflow's filters excluded this event"
        self.db.commit()

    def mark_dead(self, trigger_event_id: uuid.UUID) -> None:
        """Called once the outbox gives up: retrying deliveries become failed."""
        event = self.db.get(GHLWorkflowTriggerEvent, trigger_event_id)
        if event is None:
            return
        for delivery in self.db.scalars(
            select(GHLWorkflowTriggerDelivery).where(
                GHLWorkflowTriggerDelivery.event_id == event.id,
                GHLWorkflowTriggerDelivery.status.in_(("pending", "retrying")),
            )
        ):
            delivery.status = "failed"
        if event.status not in {"delivered", "no_subscriber"}:
            delivered = self.db.scalar(
                select(GHLWorkflowTriggerDelivery.id).where(
                    GHLWorkflowTriggerDelivery.event_id == event.id,
                    GHLWorkflowTriggerDelivery.status == "delivered",
                )
            )
            event.status = "partially_delivered" if delivered else "failed"
            event.last_error = event.last_error or "Delivery stopped after the maximum number of attempts"


class WorkflowTriggerStatusService:
    """Tenant-scoped status and manual retry for the booking UI."""

    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id

    def _order(self, order_id: uuid.UUID) -> BookingOrder:
        order = self.db.scalar(
            select(BookingOrder).where(
                BookingOrder.id == order_id, BookingOrder.operator_id == self.operator_id
            )
        )
        if order is None:
            raise NotFoundError("Order not found")
        return order

    def subscriptions(self) -> list[dict[str, Any]]:
        rows = self.db.scalars(
            select(GHLWorkflowTriggerSubscription)
            .where(GHLWorkflowTriggerSubscription.operator_id == self.operator_id)
            .order_by(GHLWorkflowTriggerSubscription.created_at)
        )
        return [
            {
                "id": row.id,
                "trigger_key": row.trigger_key,
                "trigger_version": row.trigger_version,
                "ghl_workflow_id": row.ghl_workflow_id,
                "status": row.status,
                "filters": row.filters or [],
                "last_callback_event": row.last_callback_event,
                "last_callback_at": row.last_callback_at,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    def order_status(self, order_id: uuid.UUID) -> dict[str, Any]:
        order = self._order(order_id)
        events = list(
            self.db.scalars(
                select(GHLWorkflowTriggerEvent)
                .where(
                    GHLWorkflowTriggerEvent.booking_order_id == order.id,
                    GHLWorkflowTriggerEvent.operator_id == self.operator_id,
                )
                .order_by(GHLWorkflowTriggerEvent.created_at)
            )
        )
        deliveries: dict[uuid.UUID, list[dict[str, Any]]] = {}
        if events:
            rows = self.db.execute(
                select(GHLWorkflowTriggerDelivery, GHLWorkflowTriggerSubscription.ghl_workflow_id)
                .join(
                    GHLWorkflowTriggerSubscription,
                    GHLWorkflowTriggerSubscription.id == GHLWorkflowTriggerDelivery.subscription_id,
                )
                .where(
                    GHLWorkflowTriggerDelivery.event_id.in_([event.id for event in events]),
                    GHLWorkflowTriggerDelivery.operator_id == self.operator_id,
                )
                .order_by(GHLWorkflowTriggerDelivery.created_at)
            )
            for delivery, workflow_id in rows:
                deliveries.setdefault(delivery.event_id, []).append(
                    {
                        "ghl_workflow_id": workflow_id,
                        "status": delivery.status,
                        "attempt_count": delivery.attempt_count,
                        "last_http_status": delivery.last_http_status,
                        "last_error": delivery.last_error,
                        "last_attempt_at": delivery.last_attempt_at,
                        "delivered_at": delivery.delivered_at,
                    }
                )
        return {
            "booking_order_id": order.id,
            "events": [
                {
                    "id": event.id,
                    "event_type": event.event_type,
                    "event_id": event.event_id,
                    "status": event.status,
                    "occurred_at": event.occurred_at,
                    "delivered_at": event.delivered_at,
                    "last_error": event.last_error,
                    "deliveries": deliveries.get(event.id, []),
                }
                for event in events
            ],
        }

    def retry(self, order_id: uuid.UUID) -> int:
        """Re-queue every undelivered event of the order. Delivered workflows are skipped."""
        order = self._order(order_id)
        events = list(
            self.db.scalars(
                select(GHLWorkflowTriggerEvent).where(
                    GHLWorkflowTriggerEvent.booking_order_id == order.id,
                    GHLWorkflowTriggerEvent.operator_id == self.operator_id,
                    GHLWorkflowTriggerEvent.status != "delivered",
                )
            )
        )
        for event in events:
            for delivery in self.db.scalars(
                select(GHLWorkflowTriggerDelivery).where(
                    GHLWorkflowTriggerDelivery.event_id == event.id,
                    GHLWorkflowTriggerDelivery.status.in_(("failed", "retrying")),
                )
            ):
                delivery.status = "pending"
            event.status = "pending"
            job = self.db.scalar(
                select(OutboxJob).where(
                    OutboxJob.idempotency_key == f"workflow_trigger_event:{event.id}",
                    OutboxJob.operator_id == self.operator_id,
                )
            )
            if job is not None and job.status != "processing":
                job.status = "pending"
                job.attempt_count = 0
                job.next_attempt_at = None
                job.last_error = None
        self.db.commit()
        return len(events)
