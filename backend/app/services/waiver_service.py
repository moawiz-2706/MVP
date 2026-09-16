"""Booking waivers: one per booking, signed once, then locked.

The customer reaches the waiver through a secret link (token). The form lists
one person per booked unit: the signer (an adult, with contact details and home
address) plus everyone else. Signing snapshots the exact waiver text and the
activity, records the signer's IP and browser, and a database trigger rejects
any later change to a signed waiver.
"""

import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import Booking, BookingOrder, BookingWaiver, Operator, OperatorSettings
from app.schemas.waiver import WaiverSignRequest
from app.utils.timezone import require_timezone

# Bookings a customer can sign for. Unpaid holds and cancelled bookings cannot.
SIGNABLE_STATUSES = {"confirmed", "completed"}
ADULT_AGE = 18


def age_on(date_of_birth: date, on: date) -> int:
    return on.year - date_of_birth.year - ((on.month, on.day) < (date_of_birth.month, date_of_birth.day))


def waiver_url(token: str) -> str:
    return f"{get_settings().frontend_url.rstrip('/')}/waiver/{token}"


def _has_text(settings: OperatorSettings | None) -> bool:
    return bool(settings and settings.waiver_text and settings.waiver_text.strip())


class WaiverService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def configured(self, operator_id: uuid.UUID) -> bool:
        return _has_text(self.db.get(OperatorSettings, operator_id))

    def get(self, booking_id: uuid.UUID) -> BookingWaiver | None:
        return self.db.scalar(select(BookingWaiver).where(BookingWaiver.booking_id == booking_id))

    def ensure(self, booking: Booking) -> BookingWaiver:
        """The booking's waiver, created with a fresh secret link if it has none yet."""
        waiver = self.get(booking.id)
        if waiver is None:
            self.db.execute(
                insert(BookingWaiver)
                .values(
                    operator_id=booking.operator_id,
                    booking_id=booking.id,
                    token=secrets.token_urlsafe(24),
                    status="pending",
                    public_expires_at=datetime.now(UTC) + timedelta(days=get_settings().waiver_public_days),
                )
                .on_conflict_do_nothing(index_elements=[BookingWaiver.booking_id])
            )
            self.db.commit()
            waiver = self.get(booking.id)
        return waiver

    def links_for_bookings(self, bookings: list[Booking]) -> dict[uuid.UUID, str]:
        """Signing links for unsigned, signable bookings; empty if waivers are off."""
        if not bookings or not self.configured(bookings[0].operator_id):
            return {}
        links: dict[uuid.UUID, str] = {}
        for booking in bookings:
            if booking.status not in SIGNABLE_STATUSES:
                continue
            waiver = self.ensure(booking)
            if waiver.status != "signed":
                links[booking.id] = waiver_url(waiver.token)
        return links

    def summary(self, booking: Booking) -> dict[str, Any]:
        waiver = self.get(booking.id)
        if waiver and waiver.status == "signed":
            return {"status": "signed", "signed_at": waiver.signed_at, "url": waiver_url(waiver.token)}
        if not self.configured(booking.operator_id):
            return {"status": "not_set_up", "signed_at": None, "url": None}
        if booking.status not in SIGNABLE_STATUSES:
            return {"status": "not_applicable", "signed_at": None, "url": None}
        waiver = waiver or self.ensure(booking)
        return {"status": "pending", "signed_at": None, "url": waiver_url(waiver.token)}

    def _row(self, token: str, *, lock: bool = False):
        statement = (
            select(BookingWaiver, Booking, BookingOrder, Operator, OperatorSettings)
            .join(Booking, Booking.id == BookingWaiver.booking_id)
            .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
            .join(Operator, Operator.id == BookingWaiver.operator_id)
            .outerjoin(OperatorSettings, OperatorSettings.operator_id == Operator.id)
            .where(BookingWaiver.token == token)
        )
        if lock:
            statement = statement.with_for_update(of=BookingWaiver)
        row = self.db.execute(statement).one_or_none()
        if row is None:
            raise NotFoundError("Waiver not found")
        return row

    def public_view(self, token: str) -> dict[str, Any]:
        row = self._row(token)
        waiver = row[0]
        expires_at = waiver.public_expires_at or (waiver.created_at + timedelta(days=get_settings().waiver_public_days))
        if expires_at <= datetime.now(UTC):
            raise NotFoundError("Waiver link has expired")
        return self._view(*row)

    def _view(self, waiver, booking, order, operator, settings) -> dict[str, Any]:
        base = {
            "operator_name": operator.name,
            "website": settings.waiver_website if settings else None,
            "time_zone": operator.time_zone,
            "participants_total": booking.units,
            "activity_end_at": booking.end_at,
        }
        default_title = f"{operator.name} Waiver"
        if waiver.status == "signed":
            # Everything legally meaningful comes from the snapshot, not current settings.
            return {
                **base,
                "status": "signed",
                "title": waiver.waiver_title or default_title,
                "activity_name": waiver.activity_name or booking.calendar_name_snapshot,
                "activity_start_at": waiver.activity_start_at or booking.start_at,
                "waiver_text": waiver.waiver_text,
                "opt_in_label": None,
                "signed_at": waiver.signed_at,
            }
        common = {
            **base,
            "title": (settings.waiver_title if settings else None) or default_title,
            "activity_name": booking.calendar_name_snapshot,
            "activity_start_at": booking.start_at,
            "opt_in_label": settings.waiver_opt_in_label if settings else None,
        }
        reason = None
        if not _has_text(settings):
            reason = "This waiver is not available yet. Please contact the business."
        elif booking.status not in SIGNABLE_STATUSES:
            reason = "This booking is no longer active, so its waiver cannot be signed."
        if reason:
            return {**common, "status": "unavailable", "unavailable_reason": reason, "waiver_text": None}
        return {
            **common,
            "status": "pending",
            "waiver_text": settings.waiver_text,
            "prefill": {
                "first_name": order.customer_first_name,
                "last_name": order.customer_last_name,
                "email": order.customer_email,
                "phone": order.customer_phone,
            },
        }

    def sign(
        self, token: str, data: WaiverSignRequest, *, ip: str | None, user_agent: str | None
    ) -> dict[str, Any]:
        # The row lock serializes two people signing the same link at once.
        waiver, booking, order, operator, settings = self._row(token, lock=True)
        expires_at = waiver.public_expires_at or (
            waiver.created_at + timedelta(days=get_settings().waiver_public_days)
        )
        if expires_at <= datetime.now(UTC):
            raise NotFoundError("Waiver link has expired")
        if waiver.status == "signed":
            raise ConflictError("This waiver has already been signed")
        if not _has_text(settings):
            raise ConflictError("This waiver is not available yet")
        if booking.status not in SIGNABLE_STATUSES:
            raise ConflictError("This booking is no longer active")
        people = 1 + len(data.participants)
        if people != booking.units:
            noun = "person" if booking.units == 1 else "people"
            raise ConflictError(
                f"This booking is for {booking.units} {noun}; please list everyone taking part"
            )
        zone = require_timezone(operator.time_zone)
        today = datetime.now(UTC).astimezone(zone).date()
        activity_day = booking.start_at.astimezone(zone).date()
        if any(person.date_of_birth > today for person in [data.signer, *data.participants]):
            raise ConflictError("A date of birth is in the future")
        if age_on(data.signer.date_of_birth, today) < ADULT_AGE:
            raise ConflictError("The person signing must be 18 or older")

        waiver.status = "signed"
        waiver.signed_at = datetime.now(UTC)
        waiver.signer_ip = (ip or "")[:100] or None
        waiver.signer_user_agent = (user_agent or "")[:500] or None
        waiver.waiver_title = settings.waiver_title or f"{operator.name} Waiver"
        waiver.waiver_text = settings.waiver_text
        waiver.activity_name = booking.calendar_name_snapshot
        waiver.activity_start_at = booking.start_at
        waiver.details = {
            "signer": data.signer.model_dump(mode="json"),
            "address": data.address.model_dump(mode="json"),
            "participants": [
                {
                    **person.model_dump(mode="json"),
                    "minor": age_on(person.date_of_birth, activity_day) < ADULT_AGE,
                }
                for person in data.participants
            ],
            "opt_in": bool(data.opt_in and settings.waiver_opt_in_label),
            "opt_in_label": settings.waiver_opt_in_label,
        }
        waiver.signature_png = data.signature_png
        self.db.commit()
        return self._view(waiver, booking, order, operator, settings)
