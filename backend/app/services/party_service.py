"""The guest-details page a staff booking's QR code opens.

Everyone in the party scans the code and fills in their own waiver (name,
date of birth, phone, email). The link only shows the booking's waivers: it
cannot cancel, reschedule or see payment details, so it is safe to share
with the whole group. It lasts as long as a waiver link does.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.models.entities import Booking, BookingOrder, Operator
from app.services.public_access_service import PublicAccessService
from app.services.waiver_service import SIGNABLE_STATUSES, WaiverService, waiver_url

PURPOSE = "party_details"
ACTIVE_STATUSES = SIGNABLE_STATUSES | {"pending_payment"}


def party_url(token: str) -> str:
    return f"{get_settings().frontend_url.rstrip('/')}/party/{token}"


class PartyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def issue_link(self, order: BookingOrder) -> str:
        token = PublicAccessService(self.db).issue(
            operator_id=order.operator_id,
            order_id=order.id,
            purpose=PURPOSE,
            lifetime=timedelta(days=get_settings().waiver_public_days),
        )
        self.db.commit()
        return party_url(token)

    def view(self, token: str) -> dict[str, Any]:
        credential = PublicAccessService(self.db).verify(token, purpose=PURPOSE, touch=False)
        order = self.db.get(BookingOrder, credential.order_id) if credential.order_id else None
        operator = self.db.get(Operator, order.operator_id) if order else None
        if order is None or operator is None:
            raise NotFoundError("Access link not found")
        waivers = WaiverService(self.db)
        enabled = waivers.configured(operator.id)
        bookings = list(
            self.db.scalars(
                select(Booking)
                .where(Booking.booking_order_id == order.id, Booking.status.in_(ACTIVE_STATUSES))
                .order_by(Booking.start_at)
            )
        )
        items = []
        for booking in bookings:
            ready = enabled and booking.status in SIGNABLE_STATUSES
            guests = []
            if ready:
                per_guest = waivers.per_guest(booking)
                for waiver in waivers.guest_waivers(booking):
                    signer = (waiver.details or {}).get("signer") or {} if waiver.status == "signed" else {}
                    guests.append(
                        {
                            "guest_number": waiver.guest_number,
                            "label": f"Guest {waiver.guest_number}" if per_guest else "Whole party",
                            "url": waiver_url(waiver.token),
                            "signed": waiver.status == "signed",
                            "signed_by": " ".join(
                                part for part in (signer.get("first_name"), signer.get("last_name")) if part
                            ) or None,
                        }
                    )
            items.append(
                {
                    "booking_id": booking.id,
                    "calendar_name": booking.calendar_name_snapshot,
                    "start_at": booking.start_at,
                    "units": booking.units,
                    "per_guest": waivers.per_guest(booking),
                    "waivers_open": ready,
                    "guests": guests,
                }
            )
        return {
            "operator_name": operator.name,
            "public_reference": order.public_reference,
            "customer_first_name": order.customer_first_name,
            "time_zone": operator.time_zone or "UTC",
            "waivers_enabled": enabled,
            "items": items,
        }


def order_for_reference(db: Session, operator_id: uuid.UUID, reference: str) -> BookingOrder:
    order = db.scalar(
        select(BookingOrder).where(
            BookingOrder.operator_id == operator_id, BookingOrder.public_reference == reference
        )
    )
    if order is None:
        raise NotFoundError("Booking not found")
    return order
