"""Booking waivers: one per booking, signed once, then locked.

The customer reaches the waiver through a secret link (token). The form lists
one person per booked unit: the signer (an adult, with contact details and home
address) plus everyone else. Signing snapshots the exact waiver text and the
activity, records the signer's IP and browser, and a database trigger rejects
any later change to a signed waiver.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import (
    Booking,
    BookingOrder,
    BookingParticipant,
    BookingWaiver,
    Operator,
    OperatorSettings,
)
from app.schemas.waiver import WaiverSignRequest
from app.utils.timezone import require_timezone

# Bookings a customer can sign for. Unpaid holds and cancelled bookings cannot.
SIGNABLE_STATUSES = {"confirmed", "completed"}
ADULT_AGE = 18


def age_on(date_of_birth: date, on: date) -> int:
    return on.year - date_of_birth.year - ((on.month, on.day) < (date_of_birth.month, date_of_birth.day))


def waiver_url(token: str) -> str:
    return f"{get_settings().frontend_url.rstrip('/')}/waiver/{token}"


def waiver_token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _has_text(settings: OperatorSettings | None) -> bool:
    return bool(settings and settings.waiver_text and settings.waiver_text.strip())


class WaiverService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def configured(self, operator_id: uuid.UUID) -> bool:
        return _has_text(self.db.get(OperatorSettings, operator_id))

    def get(self, booking_id: uuid.UUID, guest_number: int = 1) -> BookingWaiver | None:
        return self.db.scalar(
            select(BookingWaiver).where(
                BookingWaiver.booking_id == booking_id, BookingWaiver.guest_number == guest_number
            )
        )

    def per_guest(self, booking: Booking) -> bool:
        """Staff asked for a separate waiver for every guest of this booking."""
        order = self.db.get(BookingOrder, booking.booking_order_id)
        return bool(order and order.waiver_mode == "per_guest")

    def ensure(self, booking: Booking, guest_number: int = 1) -> BookingWaiver:
        """A guest's waiver (guest 1 = the party waiver), created with a fresh secret link."""
        waiver = self.get(booking.id, guest_number)
        if waiver is None:
            token = secrets.token_urlsafe(24)
            self.db.execute(
                insert(BookingWaiver)
                .values(
                    operator_id=booking.operator_id,
                    booking_id=booking.id,
                    guest_number=guest_number,
                    token=token,
                    token_digest=waiver_token_digest(token),
                    status="pending",
                    public_expires_at=datetime.now(UTC) + timedelta(days=get_settings().waiver_public_days),
                )
                .on_conflict_do_nothing(constraint="uq_booking_waivers_booking_guest")
            )
            self.db.commit()
            waiver = self.get(booking.id, guest_number)
        return waiver

    def guest_waivers(self, booking: Booking) -> list[BookingWaiver]:
        """Every waiver the booking needs: one per guest, or the single party waiver."""
        count = max(1, booking.units) if self.per_guest(booking) else 1
        return [self.ensure(booking, number) for number in range(1, count + 1)]

    def links_for_bookings(self, bookings: list[Booking]) -> dict[uuid.UUID, str]:
        """Signing links for unsigned, signable bookings; empty if waivers are off.

        A per-guest booking lists one line per guest still to sign.
        """
        if not bookings or not self.configured(bookings[0].operator_id):
            return {}
        links: dict[uuid.UUID, str] = {}
        for booking in bookings:
            if booking.status not in SIGNABLE_STATUSES:
                continue
            waivers = self.guest_waivers(booking)
            open_links = [
                (waiver.guest_number, waiver_url(waiver.token)) for waiver in waivers if waiver.status != "signed"
            ]
            if not open_links:
                continue
            if len(waivers) == 1:
                links[booking.id] = open_links[0][1]
            else:
                links[booking.id] = "\n".join(f"Guest {number}: {url}" for number, url in open_links)
        return links

    def guest_rows(self, booking: Booking) -> list[dict[str, Any]]:
        """Per-guest waiver state for staff screens (empty for a party waiver)."""
        if not self.per_guest(booking) or booking.status not in SIGNABLE_STATUSES or not self.configured(booking.operator_id):
            return []
        rows = []
        for waiver in self.guest_waivers(booking):
            signer = ((waiver.details or {}).get("signer") or {}) if waiver.status == "signed" else {}
            rows.append(
                {
                    "guest_number": waiver.guest_number,
                    "status": waiver.status,
                    "url": waiver_url(waiver.token),
                    "signed_at": waiver.signed_at,
                    "signed_by": " ".join(
                        part for part in (signer.get("first_name"), signer.get("last_name")) if part
                    ) or None,
                }
            )
        return rows

    def summary(self, booking: Booking) -> dict[str, Any]:
        if self.per_guest(booking) and booking.status in SIGNABLE_STATUSES and self.configured(booking.operator_id):
            waivers = self.guest_waivers(booking)
            signed = [waiver for waiver in waivers if waiver.status == "signed"]
            done = len(signed) == len(waivers)
            pending_links = [
                f"Guest {waiver.guest_number}: {waiver_url(waiver.token)}" for waiver in waivers if waiver.status != "signed"
            ]
            return {
                "status": "signed" if done else "pending",
                "signed_at": max(waiver.signed_at for waiver in signed) if done else None,
                "url": "\n".join(pending_links) if pending_links else waiver_url(waivers[0].token),
                "signed_count": len(signed),
                "total": len(waivers),
            }
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
            .where(BookingWaiver.token_digest == waiver_token_digest(token))
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
        per_guest = order.waiver_mode == "per_guest"
        base = {
            "operator_name": operator.name,
            "website": settings.waiver_website if settings else None,
            "time_zone": operator.time_zone,
            # A per-guest waiver covers one person; a party waiver everyone.
            "participants_total": 1 if per_guest else booking.units,
            "guest_number": waiver.guest_number if per_guest else None,
            "guest_total": booking.units if per_guest else None,
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
                "details": waiver.details or {},
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
            # Only the lead booker's own waiver is prefilled with their details.
            "prefill": {
                "first_name": order.customer_first_name,
                "last_name": order.customer_last_name,
                "email": order.customer_email,
                "phone": order.customer_phone,
            } if not per_guest or waiver.guest_number == 1 else None,
        }

    def _record_participants(
        self, booking: Booking, data: WaiverSignRequest, activity_day: date, *, signer_takes_part: bool = True
    ) -> None:
        """Put everyone named on the signed waiver onto the booking's manifest.

        People staff already entered are matched by name and left as they are;
        only missing people are added, so nobody is listed twice.
        """
        existing = list(
            self.db.scalars(
                select(BookingParticipant)
                .where(BookingParticipant.booking_id == booking.id)
                .with_for_update()
            )
        )
        known = {
            (row.first_name.casefold(), row.last_name.casefold()): row
            for row in existing
            if row.status != "cancelled"
        }
        sequence = max((row.sequence for row in existing), default=0)
        signer_name = f"{data.signer.first_name} {data.signer.last_name}"
        # A guardian signing a minor's own waiver is not on the trip themselves.
        people = [(data.signer, data.signer.email, data.signer.phone)] if signer_takes_part else []
        people += [(person, person.email, person.phone) for person in data.participants]
        for person, email, phone in people:
            key = (person.first_name.casefold(), person.last_name.casefold())
            if key in known:
                # Already listed (for example the lead booker, added at
                # checkout without these details): fill in only what is
                # missing, so HighLevel gets the phone and date of birth.
                row = known[key]
                if row is not None:
                    if not row.email and email:
                        row.email = str(email)
                    if not row.phone and phone:
                        row.phone = phone
                    if row.date_of_birth is None and person.date_of_birth:
                        row.date_of_birth = person.date_of_birth
                        row.is_minor = age_on(person.date_of_birth, activity_day) < ADULT_AGE
                continue
            known[key] = None
            sequence += 1
            minor = age_on(person.date_of_birth, activity_day) < ADULT_AGE
            self.db.add(
                BookingParticipant(
                    operator_id=booking.operator_id,
                    booking_id=booking.id,
                    sequence=sequence,
                    first_name=person.first_name,
                    last_name=person.last_name,
                    email=str(email) if email else None,
                    phone=phone,
                    date_of_birth=person.date_of_birth,
                    is_minor=minor,
                    # The adult signing the waiver signs on behalf of the minor.
                    guardian_name=signer_name if minor else None,
                    source="waiver",
                )
            )

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
        zone = require_timezone(operator.time_zone)
        today = datetime.now(UTC).astimezone(zone).date()
        activity_day = booking.start_at.astimezone(zone).date()
        per_guest = order.waiver_mode == "per_guest"
        if per_guest:
            # One waiver per guest: an adult signs for themselves, or a parent
            # or guardian signs for exactly one minor.
            if len(data.participants) > 1:
                raise ConflictError("This waiver is for one guest only")
            if data.participants and age_on(data.participants[0].date_of_birth, activity_day) >= ADULT_AGE:
                raise ConflictError("An adult guest signs their own waiver; only a minor's can be signed by a guardian")
        else:
            people = 1 + len(data.participants)
            if people != booking.units:
                noun = "person" if booking.units == 1 else "people"
                raise ConflictError(
                    f"This booking is for {booking.units} {noun}; please list everyone taking part"
                )
        if any(person.date_of_birth > today for person in [data.signer, *data.participants]):
            raise ConflictError("A date of birth is in the future")
        if age_on(data.signer.date_of_birth, today) < ADULT_AGE:
            raise ConflictError("The person signing must be 18 or older")
        for person in data.participants:
            if age_on(person.date_of_birth, activity_day) >= ADULT_AGE and not (person.email and person.phone):
                raise ConflictError(
                    f"Please add an email and phone number for {person.first_name} {person.last_name}; "
                    "every adult taking part needs contact details"
                )

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
        self._record_participants(
            booking, data, activity_day, signer_takes_part=not (per_guest and data.participants)
        )
        from app.services.ghl_booking_record_service import (
            enqueue_booking_record_sync,
            enqueue_contact_refresh,
        )

        # The HighLevel booking record shows the waiver status and link; the
        # contact gets the signer's date of birth and emergency contact.
        enqueue_booking_record_sync(self.db, get_settings(), order)
        enqueue_contact_refresh(self.db, get_settings(), order, f"waiver:{waiver.id}")
        self.db.commit()
        return self._view(waiver, booking, order, operator, settings)
