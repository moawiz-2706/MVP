"""Mirror each Passport order into the HighLevel "Passport Bookings" custom object.

One record per order (`booking_reference` is the primary display field),
linked to the customer's contact through the object's "Customer Booking"
association. Passport stays the source of truth: the record is overwritten
from the current order on every sync, and HighLevel never writes back.

Endpoints (HighLevel API v3): POST/PUT /objects/{key}/records,
GET /associations/objectKey/{key}, POST /associations/relations. The app
needs the objects/record.write and associations scopes for these calls.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import (
    Booking,
    BookingOrder,
    GHLBookingRecord,
    Operator,
    OutboxJob,
    Payment,
)

logger = logging.getLogger("passport.ghl_booking_records")
VERSION = "v3"


def enqueue_booking_record_sync(db: Session, settings: Settings, order: BookingOrder) -> None:
    """Queue a refresh of the order's HighLevel record in the caller's transaction.

    Runs in a savepoint: a failure (for example migration 048 not applied)
    is logged and never blocks the booking change being saved.
    """
    if not settings.ghl_booking_record_sync_enabled or settings.ghl_sync_mode == "disabled":
        return
    try:
        with db.begin_nested():
            db.execute(
                insert(OutboxJob)
                .values(
                    operator_id=order.operator_id,
                    booking_order_id=order.id,
                    job_type="ghl_sync_booking_record",
                    # A job per change; each run writes the order's current state.
                    idempotency_key=f"order:{order.id}:ghl_booking_record:{uuid.uuid4()}",
                    status="pending",
                )
                .on_conflict_do_nothing(index_elements=[OutboxJob.idempotency_key])
            )
    except SQLAlchemyError:
        logger.exception("Could not queue HighLevel booking record sync for order %s", order.id)


def record_properties(db: Session, order: BookingOrder) -> dict[str, str]:
    """The object's fields, by their short keys, from the committed order."""
    from app.services.waiver_service import WaiverService

    payment = db.scalar(select(Payment).where(Payment.booking_order_id == order.id))
    bookings = list(
        db.scalars(
            select(Booking)
            .where(Booking.booking_order_id == order.id, Booking.operator_id == order.operator_id)
            .order_by(Booking.start_at, Booking.id)
        )
    )
    waivers = WaiverService(db)
    statuses = list(dict.fromkeys(str(waivers.summary(booking).get("status") or "") for booking in bookings))
    return {
        "booking_reference": order.public_reference,
        "passport_booking_id": str(order.id),
        "payment_status": payment.status if payment else "",
        "invoice_status": (payment.invoice_status or "") if payment else "",
        "waiver_status": ", ".join(status for status in statuses if status),
    }


class GHLBookingRecordService:
    def __init__(self, db: Session, operator_id: uuid.UUID, settings: Settings) -> None:
        from app.services.ghl_client import GHLClient

        self.db = db
        self.operator_id = operator_id
        self.settings = settings
        self.client = GHLClient(operator_id, db)

    def sync(self, order_id: uuid.UUID) -> str:
        from app.services.ghl_client import GHLAPIError
        from app.services.ghl_contact_service import GHLContactService

        order = self.db.scalar(
            select(BookingOrder).where(
                BookingOrder.id == order_id, BookingOrder.operator_id == self.operator_id
            )
        )
        operator = self.db.get(Operator, self.operator_id)
        if order is None or operator is None:
            raise RuntimeError("Booking record order not found")
        if not order.ghl_contact_id:
            # The existing contact sync owns HighLevel contacts. It commits.
            GHLContactService(self.db, self.operator_id).sync(order.id)
            self.db.refresh(order)
        self.db.execute(
            insert(GHLBookingRecord)
            .values(operator_id=self.operator_id, booking_order_id=order.id, status="pending")
            .on_conflict_do_nothing(constraint="uq_ghl_booking_records_order")
        )
        mapping = self.db.scalar(
            select(GHLBookingRecord).where(GHLBookingRecord.booking_order_id == order.id).with_for_update()
        )
        properties = record_properties(self.db, order)
        key = self.settings.ghl_booking_object_key
        location_id = operator.ghl_location_id
        try:
            record_id = mapping.ghl_record_id
            if record_id:
                try:
                    self.client.request(
                        "PUT",
                        f"/objects/{key}/records/{record_id}",
                        version=VERSION,
                        params={"locationId": location_id},
                        json={"properties": properties},
                    )
                except GHLAPIError as exc:
                    if exc.status_code != 404:
                        raise
                    record_id = None  # deleted in HighLevel: create it again
                    mapping.contact_linked = False
            if not record_id:
                created = self.client.request(
                    "POST",
                    f"/objects/{key}/records",
                    version=VERSION,
                    json={"locationId": location_id, "properties": properties},
                )
                record = created.get("record", created)
                record_id = record.get("id") if isinstance(record, dict) else None
                if not record_id:
                    raise RuntimeError("HighLevel did not return a booking record id")
                mapping.ghl_record_id = str(record_id)
                self.db.flush()
            if order.ghl_contact_id and (
                not mapping.contact_linked or mapping.ghl_contact_id != order.ghl_contact_id
            ):
                self._link_contact(location_id, str(record_id), order.ghl_contact_id)
                mapping.contact_linked = True
                mapping.ghl_contact_id = order.ghl_contact_id
            mapping.status = "synced"
            mapping.last_error = None
            mapping.synced_at = datetime.now(UTC)
            self.db.commit()
            return str(record_id)
        except Exception as exc:
            mapping.status = "failed"
            mapping.last_error = str(exc)[:1000]
            self.db.commit()
            raise

    def _association(self, location_id: str) -> dict[str, Any]:
        key = self.settings.ghl_booking_object_key
        found = self.client.request(
            "GET",
            f"/associations/objectKey/{key}",
            version=VERSION,
            params={"locationId": location_id},
        )
        candidates = found if isinstance(found, list) else (
            found.get("associations") or found.get("data") or [found]
        )
        for association in candidates:
            if not isinstance(association, dict):
                continue
            sides = {association.get("firstObjectKey"), association.get("secondObjectKey")}
            if key in sides and "contact" in sides and association.get("id"):
                return association
        raise RuntimeError(f"No HighLevel association links {key} to contacts")

    def _link_contact(self, location_id: str, record_id: str, contact_id: str) -> None:
        from app.services.ghl_client import GHLAPIError

        association = self._association(location_id)
        contact_first = association.get("firstObjectKey") == "contact"
        try:
            self.client.request(
                "POST",
                "/associations/relations",
                version=VERSION,
                json={
                    "locationId": location_id,
                    "associationId": association["id"],
                    "firstRecordId": contact_id if contact_first else record_id,
                    "secondRecordId": record_id if contact_first else contact_id,
                },
            )
        except GHLAPIError as exc:
            # A repeated link is not an error worth retrying.
            if exc.status_code not in {400, 409} or "exist" not in str(exc).lower():
                raise
