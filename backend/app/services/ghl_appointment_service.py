from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import (
    Booking,
    BookingOrder,
    Calendar,
    GHLAppointmentMapping,
    GHLCalendarMapping,
    Operator,
    Staff,
    StaffAssignment,
)
from app.services.ghl_calendar_service import GHLCalendarService
from app.services.ghl_client import GHLClient
from app.services.ghl_contact_service import GHLContactService


class GHLAppointmentService:
    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id
        self.settings = get_settings()
        self.client = GHLClient(operator_id)

    @staticmethod
    def _appointment_title(
        booking: Booking,
        order: BookingOrder,
        staff_names: list[str] | tuple[str, ...] = (),
    ) -> str:
        contact_name = " ".join(
            part
            for part in (order.customer_first_name, order.customer_last_name)
            if part
        ).strip()
        base_unit_price = Decimal(booking.base_price_minor) / Decimal(100)
        assigned_staff = ", ".join(staff_names) if staff_names else "Unassigned"
        return f"{contact_name} – {order.currency.upper()} {base_unit_price:,.2f} and {assigned_staff}"

    def sync(self, booking_id: uuid.UUID) -> str | None:
        if not self.settings.ghl_calendar_sync_enabled:
            return None
        row = self.db.execute(
            select(Booking, BookingOrder, Calendar, Operator)
            .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
            .join(Calendar, Calendar.id == Booking.calendar_id)
            .join(Operator, Operator.id == Booking.operator_id)
            .where(Booking.id == booking_id, Booking.operator_id == self.operator_id)
        ).one_or_none()
        if row is None:
            raise RuntimeError("GHL appointment source not found")
        booking, order, calendar, operator = row
        calendar_id = GHLCalendarService(self.db, self.operator_id).sync(calendar.id)
        if not calendar_id:
            return None
        calendar_mapping = self.db.scalar(
            select(GHLCalendarMapping).where(
                GHLCalendarMapping.operator_id == self.operator_id,
                GHLCalendarMapping.calendar_id == calendar.id,
            )
        )
        if calendar_mapping is None:
            raise RuntimeError("GHL calendar mapping was not created")
        mapping = self.db.scalar(
            select(GHLAppointmentMapping).where(
                GHLAppointmentMapping.operator_id == self.operator_id,
                GHLAppointmentMapping.booking_id == booking.id,
            ).with_for_update()
        )
        if mapping is None:
            mapping = GHLAppointmentMapping(
                operator_id=self.operator_id,
                booking_id=booking.id,
                ghl_calendar_mapping_id=calendar_mapping.id,
            )
            self.db.add(mapping)
            self.db.flush()
        if not order.ghl_contact_id:
            GHLContactService(self.db, self.operator_id).sync(order.id)
            self.db.refresh(order)
        if not order.ghl_contact_id:
            raise RuntimeError("HighLevel contact is required for an appointment")
        staff_names = list(
            self.db.scalars(
                select(Staff.name)
                .join(StaffAssignment, StaffAssignment.staff_id == Staff.id)
                .where(
                    StaffAssignment.operator_id == self.operator_id,
                    StaffAssignment.calendar_id == booking.calendar_id,
                    StaffAssignment.start_at < booking.end_at,
                    StaffAssignment.end_at > booking.start_at,
                )
                .distinct()
                .order_by(Staff.name)
            )
        )
        body = {
            "calendarId": calendar_mapping.ghl_calendar_id,
            "locationId": operator.ghl_location_id,
            "contactId": order.ghl_contact_id,
            "title": self._appointment_title(booking, order, staff_names),
            "description": f"Passport booking: {booking.id}",
            "startTime": booking.start_at.isoformat(),
            "endTime": booking.end_at.isoformat(),
            "appointmentStatus": "cancelled" if booking.status == "cancelled" else "confirmed",
            "ignoreFreeSlotValidation": True,
            "toNotify": False,
        }
        payload_hash = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        try:
            if mapping.ghl_event_id:
                result = self.client.request(
                    "PUT",
                    f"/calendars/events/appointments/{mapping.ghl_event_id}",
                    version="v3",
                    json=body,
                )
            else:
                result = self.client.request(
                    "POST", "/calendars/events/appointments", version="v3", json=body
                )
            remote = result.get("appointment", result)
            remote_id = remote.get("id") if isinstance(remote, dict) else None
            if not remote_id and mapping.ghl_event_id:
                remote_id = mapping.ghl_event_id
            if not remote_id:
                raise RuntimeError("HighLevel did not return an appointment ID")
            mapping.ghl_event_id = str(remote_id)
            mapping.payload_hash = payload_hash
            mapping.applied_revision = mapping.desired_revision
            mapping.status = "synced" if booking.status != "cancelled" else "cancelled"
            mapping.last_error = None
            self.db.commit()
            return mapping.ghl_event_id
        except Exception as exc:
            mapping.status = "failed"
            mapping.last_error = str(exc)[:2000]
            self.db.commit()
            raise

    def cancel(self, booking_id: uuid.UUID) -> str | None:
        if not self.settings.ghl_calendar_sync_enabled:
            return None
        mapping = self.db.scalar(
            select(GHLAppointmentMapping).where(
                GHLAppointmentMapping.operator_id == self.operator_id,
                GHLAppointmentMapping.booking_id == booking_id,
            ).with_for_update()
        )
        if mapping is None or not mapping.ghl_event_id:
            return None
        try:
            self.client.request(
                "PUT",
                f"/calendars/events/appointments/{mapping.ghl_event_id}",
                version="v3",
                json={"appointmentStatus": "cancelled", "toNotify": False},
            )
            mapping.status = "cancelled"
            mapping.last_error = None
            self.db.commit()
            return mapping.ghl_event_id
        except Exception as exc:
            mapping.status = "failed"
            mapping.last_error = str(exc)[:2000]
            self.db.commit()
            raise
