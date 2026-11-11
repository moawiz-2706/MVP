import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Booking,
    BookingOrder,
    BookingParticipant,
    Customer,
    Operator,
    Payment,
    Staff,
)
from app.services.ghl_client import GHLClient
from app.services.waiver_service import WaiverService

# Tags the operator created in their HighLevel location. They are applied with
# the dedicated add-tags endpoint, which appends: sending `tags` on a contact
# update would replace every tag the operator's team had set on that contact.
CUSTOMER_TAG = "passport-customer"
STAFF_TAG = "passport-staff"
# Other adults in a party who gave their details on a waiver.
GUEST_TAG = "passport-guest"

logger = logging.getLogger(__name__)


def _normalized_phone(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"[^0-9+]", "", value)
    if compact.startswith("+") and compact[1:].isdigit() and 8 <= len(compact[1:]) <= 15:
        return compact
    # Operators are US based: a 10-digit local number, or 1 + 10 digits.
    if compact.isdigit() and len(compact) == 10:
        return f"+1{compact}"
    if compact.isdigit() and len(compact) == 11 and compact.startswith("1"):
        return f"+{compact}"
    return None


def _split_name(name: str) -> tuple[str, str]:
    parts = name.strip().split(maxsplit=1)
    return (parts[0] if parts else name.strip(), parts[1] if len(parts) > 1 else "")


class GHLContactService:
    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id
        self.client = GHLClient(operator_id, db)

    def sync(self, order_id: uuid.UUID) -> str:
        """Create or update the customer's Contact and tag it passport-customer."""
        order = self.db.scalar(
            select(BookingOrder).where(
                BookingOrder.id == order_id, BookingOrder.operator_id == self.operator_id
            )
        )
        operator = self.db.get(Operator, self.operator_id)
        if order is None or operator is None:
            raise RuntimeError("GHL contact order not found")
        from app.services.ghl_booking_facts import booking_facts

        facts = booking_facts(self.db, order)
        participants = self._participants(order)
        lead = self._lead(order, participants)
        contact_id = self._upsert(
            operator.ghl_location_id,
            existing_id=order.ghl_contact_id,
            first_name=order.customer_first_name,
            last_name=order.customer_last_name,
            email=order.customer_email,
            # A staff booking may have no phone; the waiver signer then gives one.
            phone=order.customer_phone or (lead.phone if lead else None),
            custom_fields=self._booking_custom_fields(order, facts),
            date_of_birth=facts.lead_date_of_birth,
        )
        self._add_tags(contact_id, [CUSTOMER_TAG])
        order.ghl_contact_id = contact_id
        order.ghl_contact_sync_status = "synced"
        customer = self.db.get(Customer, order.customer_id) if order.customer_id else None
        if customer is not None:
            customer.ghl_contact_id = contact_id
            customer.ghl_contact_sync_status = "synced"
            customer.ghl_contact_last_error = None
        self.db.commit()
        self._sync_guests(operator.ghl_location_id, participants, lead)
        return contact_id

    def _participants(self, order: BookingOrder) -> list[BookingParticipant]:
        return list(
            self.db.scalars(
                select(BookingParticipant)
                .join(Booking, Booking.id == BookingParticipant.booking_id)
                .where(
                    Booking.booking_order_id == order.id,
                    BookingParticipant.operator_id == self.operator_id,
                    BookingParticipant.status == "active",
                )
                .order_by(BookingParticipant.sequence)
            )
        )

    @staticmethod
    def _lead(order: BookingOrder, participants: list[BookingParticipant]) -> BookingParticipant | None:
        email = (order.customer_email or "").casefold()
        return next(
            (p for p in participants if email and (p.email or "").casefold() == email),
            None,
        )

    def _sync_guests(
        self,
        location_id: str,
        participants: list[BookingParticipant],
        lead: BookingParticipant | None,
    ) -> None:
        """Give every other adult who signed or was listed on a waiver their own
        Contact. Only details the Contact is missing are filled in; a failure
        for one guest never fails the customer's sync."""
        seen: set[str] = set()
        for person in participants:
            email = (person.email or "").strip()
            if person is lead or person.is_minor or not email or email.casefold() in seen:
                continue
            seen.add(email.casefold())
            try:
                contact_id = self._upsert(
                    location_id,
                    existing_id=None,
                    first_name=person.first_name,
                    last_name=person.last_name,
                    email=email,
                    phone=person.phone,
                    date_of_birth=person.date_of_birth,
                    fill_missing_only=True,
                )
                self._add_tags(contact_id, [GUEST_TAG])
                self._link_guest_to_record(location_id, person, contact_id)
            except Exception:  # noqa: BLE001 - one guest must not block the rest
                logger.warning("Could not sync HighLevel contact for guest %s", person.id, exc_info=True)

    def _link_guest_to_record(self, location_id: str, person: BookingParticipant, contact_id: str) -> None:
        """Associate a guest's contact with the booking's Passport Booking record,
        so the record lists everyone in the party, not only the lead booker."""
        from app.core.config import get_settings
        from app.models.entities import GHLBookingRecord
        from app.services.ghl_booking_record_service import GHLBookingRecordService

        settings = get_settings()
        if not settings.ghl_booking_record_sync_enabled:
            return
        booking = self.db.get(Booking, person.booking_id)
        record_id = self.db.scalar(
            select(GHLBookingRecord.ghl_record_id).where(
                GHLBookingRecord.booking_order_id == booking.booking_order_id
            )
        ) if booking else None
        if not record_id:
            return  # the record sync links guests once the record exists
        service = GHLBookingRecordService(self.db, self.operator_id, settings)
        service.client = self.client
        service._link_contact(location_id, str(record_id), contact_id)

    def _booking_custom_fields(self, order: BookingOrder, facts=None) -> list[dict[str, str]]:
        """Booking details for the contact's "Passport …" custom fields.

        Fields are found by key in the location (no manual mapping); a field
        that was not created in HighLevel is simply skipped.
        """
        from app.services.ghl_booking_facts import booking_facts, contact_values
        from app.services.ghl_field_registry import contact_field_ids

        operator = self.db.get(Operator, self.operator_id)
        values = contact_values(facts or booking_facts(self.db, order))
        field_ids = contact_field_ids(
            self.db, self.client, self.operator_id, operator.ghl_location_id, set(values)
        )
        return [
            {"id": field_ids[key], "key": key, "fieldValue": value}
            for key, value in values.items()
            if key in field_ids
        ]

    def sync_staff(self, staff_id: uuid.UUID) -> str | None:
        """Create or update a staff member's Contact and tag it passport-staff.

        Staff without an email address are skipped: they cannot receive the
        assignment emails and reminders the Contact exists for.
        """
        staff = self.db.scalar(
            select(Staff).where(Staff.id == staff_id, Staff.operator_id == self.operator_id)
        )
        operator = self.db.get(Operator, self.operator_id)
        if staff is None or operator is None or staff.deleted_at is not None or not staff.email:
            return None
        first_name, last_name = _split_name(staff.name)
        contact_id = self._upsert(
            operator.ghl_location_id,
            existing_id=staff.ghl_contact_id,
            first_name=first_name,
            last_name=last_name,
            email=staff.email,
            phone=staff.phone,
        )
        self._add_tags(contact_id, [STAFF_TAG])
        staff.ghl_contact_id = contact_id
        self.db.commit()
        return contact_id

    def _upsert(
        self,
        location_id: str,
        *,
        existing_id: str | None,
        first_name: str,
        last_name: str,
        email: str | None,
        phone: str | None,
        custom_fields: list[dict[str, str]] | None = None,
        date_of_birth=None,
        fill_missing_only: bool = False,
    ) -> str:
        """Create the Contact, or update the one already there.

        Phone and date of birth are only added when the Contact has none, so a
        number or birthday the team corrected in HighLevel is never replaced.
        With `fill_missing_only` the names are treated the same way.
        """
        contact_id = existing_id
        if not contact_id:
            contact_id = self._find_clear_match(location_id, email=email)
        normalized_phone = _normalized_phone(phone)
        if not contact_id and normalized_phone:
            contact_id = self._find_clear_match(location_id, phone=normalized_phone)

        fields = {"firstName": first_name, "email": email}
        if last_name:
            fields["lastName"] = last_name
        if normalized_phone:
            fields["phone"] = normalized_phone
        if custom_fields:
            fields["customFields"] = custom_fields
        if date_of_birth is not None:
            # The contact's standard "Date of birth", from the lead booker's waiver.
            fields["dateOfBirth"] = date_of_birth.isoformat()
        if contact_id:
            current = self.client.request("GET", f"/contacts/{contact_id}", version="v3")
            current_contact = current.get("contact", current) if isinstance(current, dict) else {}
            if not isinstance(current_contact, dict):
                current_contact = {}
            current_email = current_contact.get("email")
            if current_email and email and str(current_email).casefold() != email.casefold():
                raise RuntimeError("HighLevel contact email is immutable; manual reconciliation is required")
            if not current_email and not email:
                fields.pop("email", None)
            keep = ["phone", "dateOfBirth"]
            if fill_missing_only:
                keep += ["firstName", "lastName"]
            for key in keep:
                if key in fields and current_contact.get(key):
                    fields.pop(key)
            result = self.client.request(
                "PUT", f"/contacts/{contact_id}", version="v3", json=fields
            )
        else:
            result = self.client.request(
                "POST",
                "/contacts/",
                version="v3",
                json={"locationId": location_id, **fields},
            )
        contact = result.get("contact", result)
        resolved = contact.get("id") or contact_id
        if not resolved:
            raise RuntimeError("HighLevel did not return a Contact ID")
        return str(resolved)

    def _add_tags(self, contact_id: str, tags: list[str]) -> None:
        self.client.request(
            "POST", f"/contacts/{contact_id}/tags", version="v3", json={"tags": tags}
        )

    def _find_clear_match(
        self, location_id: str, *, email: str | None = None, phone: str | None = None
    ) -> str | None:
        params = {"locationId": location_id, "limit": 20}
        if email:
            params["email"] = email
        elif phone:
            params["phone"] = phone
        else:
            return None
        result = self.client.request("GET", "/contacts/lookup", version="v3", params=params)
        candidates = [
            contact
            for contact in result.get("contacts", [])
            if contact.get("locationId") == location_id
            and (
                email
                and str(contact.get("email", "")).casefold() == email.casefold()
                or phone
                and _normalized_phone(contact.get("phone")) == phone
            )
        ]
        if len(candidates) > 1:
            raise RuntimeError("Multiple exact HighLevel contacts matched; refusing unsafe update")
        return str(candidates[0]["id"]) if candidates else None

    def sync_booking_owner(self, order_id: uuid.UUID, user_id: str) -> str:
        """Set Passport Captain ownership, refusing global-owner conflicts."""
        order = self.db.scalar(select(BookingOrder).where(BookingOrder.id == order_id, BookingOrder.operator_id == self.operator_id))
        if order is None or not order.ghl_contact_id:
            raise RuntimeError("HighLevel contact is required before assigning a Captain")
        current = self.client.request("GET", f"/contacts/{order.ghl_contact_id}", version="v3")
        contact = current.get("contact", current) if isinstance(current, dict) else {}
        assigned = contact.get("assignedTo") if isinstance(contact, dict) else None
        if assigned and str(assigned) != user_id:
            raise RuntimeError("HighLevel contact is already owned by another user; manual review is required")
        if str(assigned or "") != user_id:
            self.client.request("PUT", f"/contacts/{order.ghl_contact_id}", version="v3", json={"assignedTo": user_id})
        return order.ghl_contact_id

    def clear_managed_owner(self, order_id: uuid.UUID) -> None:
        """Clear only an owner that is currently linked to Passport staff."""
        order = self.db.scalar(select(BookingOrder).where(BookingOrder.id == order_id, BookingOrder.operator_id == self.operator_id))
        if order is None or not order.ghl_contact_id:
            return
        current = self.client.request("GET", f"/contacts/{order.ghl_contact_id}", version="v3")
        contact = current.get("contact", current) if isinstance(current, dict) else {}
        assigned = contact.get("assignedTo") if isinstance(contact, dict) else None
        if not assigned:
            return
        managed = self.db.scalar(select(Staff.id).where(Staff.operator_id == self.operator_id, Staff.ghl_user_id == str(assigned)))
        if managed is not None:
            self.client.request("PUT", f"/contacts/{order.ghl_contact_id}", version="v3", json={"assignedTo": None})
