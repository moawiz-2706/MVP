from __future__ import annotations

import hashlib
import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import (
    Booking,
    BookingOrder,
    BookingResource,
    Calendar,
    GHLAppointmentMapping,
    GHLCalendarMapping,
    Operator,
    Resource,
    Staff,
    StaffAssignment,
)
from app.services.ghl_calendar_service import GHLCalendarService
from app.services.ghl_client import GHLAPIError, GHLClient
from app.services.ghl_contact_service import GHLContactService

logger = logging.getLogger("passport.ghl_appointment")


class GHLAppointmentService:
    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id
        self.settings = get_settings()
        self.client = GHLClient(operator_id)

    def _description(
        self,
        booking: Booking,
        order: BookingOrder,
        calendar: Calendar,
        resources: list[tuple[str, int]],
        staff: list[tuple[str, str | None]],
    ) -> str:
        resource_lines = "\n".join(f"- {name}: {quantity}" for name, quantity in resources) or "- None"
        staff_lines = "\n".join(
            f"- {name}{f' ({role})' if role else ''}" for name, role in staff
        ) or "- None"
        return "\n".join(
            [
                "Passport booking",
                f"Reference: {order.public_reference}",
                f"Booking ID: {booking.id}",
                f"Service: {calendar.name}",
                f"Customer: {order.customer_first_name} {order.customer_last_name}",
                f"Email: {order.customer_email}",
                f"Phone: {order.customer_phone or 'Not provided'}",
                f"Quantity: {booking.units}",
                f"Location: {booking.departure_location_name_snapshot or 'Not assigned'}",
                f"Address: {booking.departure_location_address_snapshot or 'Not provided'}",
                "Resources:",
                resource_lines,
                "Staff:",
                staff_lines,
            ]
        )

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
            select(GHLAppointmentMapping)
            .where(
                GHLAppointmentMapping.operator_id == self.operator_id,
                GHLAppointmentMapping.booking_id == booking.id,
            )
            .with_for_update()
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

        resources = self.db.execute(
            select(Resource.name, BookingResource.quantity)
            .join(BookingResource, BookingResource.resource_id == Resource.id)
            .where(BookingResource.booking_id == booking.id)
            .order_by(Resource.name)
        ).all()
        staff = self.db.execute(
            select(Staff.name, StaffAssignment.role)
            .join(StaffAssignment, StaffAssignment.staff_id == Staff.id)
            .where(
                StaffAssignment.operator_id == self.operator_id,
                StaffAssignment.calendar_id == booking.calendar_id,
                StaffAssignment.start_at < booking.end_at,
                StaffAssignment.end_at > booking.start_at,
            )
            .order_by(Staff.name)
        ).all()
        body = {
            "calendarId": calendar_mapping.ghl_calendar_id,
            "locationId": operator.ghl_location_id,
            "contactId": order.ghl_contact_id,
            "title": f"{calendar.name} — {order.customer_first_name} {order.customer_last_name}",
            "description": self._description(booking, order, calendar, resources, staff),
            "startTime": booking.start_at.isoformat(),
            "endTime": booking.end_at.isoformat(),
            "appointmentStatus": "cancelled" if booking.status == "cancelled" else "confirmed",
            "ignoreFreeSlotValidation": True,
            "toNotify": False,
        }
        payload_hash = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        operation = "update" if mapping.ghl_event_id else "create"
        try:
            if mapping.ghl_event_id:
                try:
                    result = self.client.request(
                        "PUT",
                        f"/calendars/events/appointments/{mapping.ghl_event_id}",
                        version="v3",
                        json=body,
                    )
                except GHLAPIError as exc:
                    if exc.status_code != 404:
                        raise
                    logger.warning(
                        "GHL appointment disappeared; recreating booking_id=%s ghl_calendar_id=%s ghl_appointment_id=%s",
                        booking.id,
                        calendar_mapping.ghl_calendar_id,
                        mapping.ghl_event_id,
                    )
                    mapping.ghl_event_id = None
                    operation = "recreate"
                    result = self.client.request(
                        "POST", "/calendars/events/appointments", version="v3", json=body
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
            logger.info(
                "GHL appointment %s succeeded booking_id=%s ghl_calendar_id=%s ghl_appointment_id=%s",
                operation,
                booking.id,
                calendar_mapping.ghl_calendar_id,
                mapping.ghl_event_id,
            )
            return mapping.ghl_event_id
        except Exception as exc:
            mapping.status = "failed"
            mapping.last_error = str(exc)[:2000]
            self.db.commit()
            logger.error(
                "GHL appointment sync failed operation=%s booking_id=%s ghl_calendar_id=%s ghl_appointment_id=%s error=%s",
                operation,
                booking.id,
                calendar_mapping.ghl_calendar_id,
                mapping.ghl_event_id,
                str(exc)[:1000],
            )
            raise

    def cancel(self, booking_id: uuid.UUID) -> str | None:
        if not self.settings.ghl_calendar_sync_enabled:
            return None
        mapping = self.db.scalar(
            select(GHLAppointmentMapping)
            .where(
                GHLAppointmentMapping.operator_id == self.operator_id,
                GHLAppointmentMapping.booking_id == booking_id,
            )
            .with_for_update()
        )
        if mapping is None or not mapping.ghl_event_id:
            return None
        event_id = mapping.ghl_event_id
        try:
            self.client.request(
                "PUT",
                f"/calendars/events/appointments/{event_id}",
                version="v3",
                json={"appointmentStatus": "cancelled", "toNotify": False},
            )
            mapping.status = "cancelled"
            mapping.last_error = None
            self.db.commit()
            logger.info(
                "GHL appointment cancel succeeded booking_id=%s ghl_appointment_id=%s",
                booking_id,
                event_id,
            )
            return event_id
        except GHLAPIError as exc:
            if exc.status_code == 404:
                mapping.status = "cancelled"
                mapping.last_error = None
                self.db.commit()
                logger.info(
                    "GHL appointment already absent during cancel booking_id=%s ghl_appointment_id=%s",
                    booking_id,
                    event_id,
                )
                return event_id
            mapping.status = "failed"
            mapping.last_error = str(exc)[:2000]
            self.db.commit()
            logger.error(
                "GHL appointment cancel failed booking_id=%s ghl_appointment_id=%s error=%s",
                booking_id,
                event_id,
                str(exc)[:1000],
            )
            raise
