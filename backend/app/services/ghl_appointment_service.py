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
from app.services.ghl_staff_user_service import GHLStaffUserService


class GHLAppointmentService:
    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id
        self.settings = get_settings()
        self.client = GHLClient(operator_id, db)

    @staticmethod
    def _appointment_title(
        booking: Booking,
        order: BookingOrder,
        staff_names: list[str] | tuple[str, ...] = (),
    ) -> str:
        contact_name = " ".join(
            part for part in (order.customer_first_name, order.customer_last_name) if part
        ).strip()
        base_unit_price = Decimal(booking.base_price_minor) / Decimal(100)
        assigned_staff = ", ".join(staff_names) if staff_names else "Unassigned"
        return (
            f"{contact_name} – {order.currency.upper()} {base_unit_price:,.2f}"
            f" and {assigned_staff}"
        )

    def _appointment_description(
        self,
        booking: Booking,
        order: BookingOrder,
        calendar: Calendar,
        staff_names: list[str],
    ) -> str:
        resources = [
            f"{name} × {quantity}"
            for name, quantity in self.db.execute(
                select(Resource.name, BookingResource.quantity)
                .join(BookingResource, BookingResource.resource_id == Resource.id)
                .where(BookingResource.booking_id == booking.id)
                .order_by(Resource.name)
            )
        ]
        lines = [
            f"Passport booking: {booking.id}",
            f"Reference: {order.public_reference}",
            f"Service: {calendar.name}",
            f"Customer email: {order.customer_email}",
            f"Customer phone: {order.customer_phone or 'Not provided'}",
            f"Status: {booking.status}",
            f"Quantity: {booking.units}",
            f"Base unit price: {order.currency.upper()} {booking.base_price_minor / 100:,.2f}",
            "Assigned staff: " + (", ".join(staff_names) if staff_names else "Unassigned"),
            "Resources: " + (", ".join(resources) if resources else "None"),
        ]
        return "\n".join(lines)

    @staticmethod
    def _appointment_status(booking: Booking) -> str:
        return {
            "pending_payment": "new",
            "confirmed": "confirmed",
            "cancelled": "cancelled",
            "completed": "completed",
            "no_show": "noshow",
            "failed": "invalid",
        }.get(booking.status, "confirmed")

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
        if booking.status == "cancelled" and mapping is None:
            # A cancellation may race the initial appointment job. There is no
            # remote appointment to cancel, and creating a cancelled event is wrong.
            return None
        if mapping is not None and mapping.ghl_event_id is None and mapping.status == "manual_review":
            raise RuntimeError(
                "HighLevel appointment create outcome is unknown; reconcile the remote event before retrying"
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
        captain_user_id = None
        from app.services.staffing_service import readiness_for_booking

        readiness = readiness_for_booking(self.db, booking)
        if readiness.ready and readiness.assignment_id:
            captain_staff_id = self.db.scalar(
                select(StaffAssignment.staff_id).where(StaffAssignment.id == readiness.assignment_id)
            )
            if captain_staff_id:
                captain_user_id = GHLStaffUserService(
                    self.db, self.operator_id
                ).verified_active_user_id(captain_staff_id)
            if captain_user_id:
                GHLContactService(self.db, self.operator_id).sync_booking_owner(
                    order.id, captain_user_id
                )
        else:
            GHLContactService(self.db, self.operator_id).clear_managed_owner(order.id)
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
            "description": self._appointment_description(booking, order, calendar, staff_names),
            "startTime": booking.start_at.isoformat(),
            "endTime": booking.end_at.isoformat(),
            "appointmentStatus": self._appointment_status(booking),
            "ignoreFreeSlotValidation": True,
            "toNotify": False,
        }
        if captain_user_id:
            body["assignedUserId"] = captain_user_id
        payload_hash = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
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
                    # The event may have been deleted directly in GHL. Clear the
                    # stale ID and recreate it once, preserving idempotent mapping.
                    mapping.ghl_event_id = None
                    self.db.flush()
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
            return mapping.ghl_event_id
        except Exception as exc:
            mapping.status = "failed"
            mapping.last_error = str(exc)[:2000]
            if mapping.ghl_event_id is None:
                mapping.status = "manual_review"
                mapping.last_error = (
                    "HighLevel appointment create outcome is unknown; reconcile the remote event "
                    "before retrying"
                )
            self.db.commit()
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
        except GHLAPIError as exc:
            if exc.status_code == 404:
                mapping.ghl_event_id = None
                mapping.status = "cancelled"
                mapping.last_error = "Remote HighLevel appointment was already deleted"
                self.db.commit()
                return None
            mapping.status = "failed"
            mapping.last_error = str(exc)[:2000]
            self.db.commit()
            raise
        except Exception as exc:
            mapping.status = "failed"
            mapping.last_error = str(exc)[:2000]
            self.db.commit()
            raise

    def get(self, booking_id: uuid.UUID) -> dict | None:
        """Retrieve the mapped remote appointment for diagnostics and reconciliation."""
        if not self.settings.ghl_calendar_sync_enabled:
            return None
        mapping = self.db.scalar(
            select(GHLAppointmentMapping).where(
                GHLAppointmentMapping.operator_id == self.operator_id,
                GHLAppointmentMapping.booking_id == booking_id,
            )
        )
        if mapping is None or not mapping.ghl_event_id:
            return None
        try:
            result = self.client.request(
                "GET",
                f"/calendars/events/appointments/{mapping.ghl_event_id}",
                version="2021-04-15",
            )
        except GHLAPIError as exc:
            if exc.status_code == 404:
                mapping.ghl_event_id = None
                mapping.status = "failed"
                mapping.last_error = "Remote HighLevel appointment no longer exists"
                self.db.commit()
                return None
            raise
        return result.get("event", result) if isinstance(result, dict) else None
