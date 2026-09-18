import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import BookingOrder, Operator, Staff
from app.services.ghl_client import GHLClient

# Tags the operator created in their HighLevel location. They are applied with
# the dedicated add-tags endpoint, which appends: sending `tags` on a contact
# update would replace every tag the operator's team had set on that contact.
CUSTOMER_TAG = "passport-customer"
STAFF_TAG = "passport-staff"


def _normalized_phone(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"[^0-9+]", "", value)
    if compact.startswith("+") and compact[1:].isdigit() and 8 <= len(compact[1:]) <= 15:
        return compact
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
        contact_id = self._upsert(
            operator.ghl_location_id,
            existing_id=order.ghl_contact_id,
            first_name=order.customer_first_name,
            last_name=order.customer_last_name,
            email=order.customer_email,
            phone=order.customer_phone,
        )
        self._add_tags(contact_id, [CUSTOMER_TAG])
        order.ghl_contact_id = contact_id
        order.ghl_contact_sync_status = "synced"
        self.db.commit()
        return contact_id

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
    ) -> str:
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
        if contact_id:
            current = self.client.request("GET", f"/contacts/{contact_id}", version="v3")
            current_contact = current.get("contact", current) if isinstance(current, dict) else {}
            current_email = current_contact.get("email") if isinstance(current_contact, dict) else None
            if current_email and email and str(current_email).casefold() != email.casefold():
                raise RuntimeError("HighLevel contact email is immutable; manual reconciliation is required")
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
