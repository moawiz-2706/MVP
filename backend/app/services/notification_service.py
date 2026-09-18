from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Booking,
    BookingOrder,
    Calendar,
    CalendarDateHour,
    CalendarHour,
    CalendarPushedSlot,
    CalendarResource,
    StaffAssignment,
)
from app.schemas.notifications import NotificationItem, NotificationsResponse
from app.services.staffing_service import readiness_for_booking


class NotificationService:
    """Derives actionable notifications from the current tenant database state."""

    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id

    def list(self) -> NotificationsResponse:
        now = datetime.now(UTC)
        items: list[NotificationItem] = []
        calendars = list(
            self.db.scalars(
                select(Calendar)
                .where(
                    Calendar.operator_id == self.operator_id,
                    Calendar.deleted_at.is_(None),
                    Calendar.is_active.is_(True),
                )
                .order_by(Calendar.name)
            )
        )
        calendar_ids = [calendar.id for calendar in calendars]
        if calendar_ids:
            items.extend(self._calendar_items(calendars))
            items.extend(self._booking_items(now, calendar_ids))
        items.sort(key=self._sort_key)
        return NotificationsResponse(
            items=items,
            pending_count=len(items),
            generated_at=now,
        )

    def _calendar_items(self, calendars: list[Calendar]) -> list[NotificationItem]:
        ids = [calendar.id for calendar in calendars]
        hours = set(
            self.db.scalars(
                select(CalendarHour.calendar_id).where(CalendarHour.calendar_id.in_(ids))
            )
        )
        date_hours = set(
            self.db.scalars(
                select(CalendarDateHour.calendar_id).where(CalendarDateHour.calendar_id.in_(ids))
            )
        )
        pushed = set(
            self.db.scalars(
                select(CalendarPushedSlot.calendar_id).where(CalendarPushedSlot.calendar_id.in_(ids))
            )
        )
        resources = set(
            self.db.scalars(
                select(CalendarResource.calendar_id).where(CalendarResource.calendar_id.in_(ids))
            )
        )
        result: list[NotificationItem] = []
        for calendar in calendars:
            has_availability = {
                "day_wise": calendar.id in hours,
                "date_wise": calendar.id in date_hours,
                "pushed": calendar.id in pushed,
            }.get(calendar.availability_mode, False)
            if not has_availability:
                mode_label = {
                    "day_wise": "weekly hours",
                    "date_wise": "date ranges",
                    "pushed": "pushed time slots",
                }.get(calendar.availability_mode, "availability")
                result.append(
                    NotificationItem(
                        id=f"calendar-availability:{calendar.id}",
                        type="calendar_availability",
                        title=f"Configure availability for {calendar.name}",
                        description=(
                            f"This calendar has no saved {mode_label}. "
                            "Add availability before accepting bookings."
                        ),
                        action_label="Configure availability",
                        calendar_id=calendar.id,
                        calendar_name=calendar.name,
                    )
                )
            if not resources:
                result.append(
                    NotificationItem(
                        id=f"calendar-resources:{calendar.id}",
                        type="calendar_resources",
                        title=f"Configure resources for {calendar.name}",
                        description=(
                            "No resources are mapped to this calendar. Add the required "
                            "resource pools before booking."
                        ),
                        action_label="Configure resources",
                        calendar_id=calendar.id,
                        calendar_name=calendar.name,
                    )
                )
            elif calendar.id not in resources:
                result.append(
                    NotificationItem(
                        id=f"calendar-resources:{calendar.id}",
                        type="calendar_resources",
                        title=f"Configure resources for {calendar.name}",
                        description=(
                            "This calendar has no mapped resources. Attach the resource "
                            "pools needed for its bookings."
                        ),
                        action_label="Configure resources",
                        calendar_id=calendar.id,
                        calendar_name=calendar.name,
                    )
                )
        return result

    def _booking_items(
        self, now: datetime, calendar_ids: list[uuid.UUID]
    ) -> list[NotificationItem]:
        conditions = [
            Booking.operator_id == self.operator_id,
            Booking.calendar_id.in_(calendar_ids),
            Booking.status.in_(("confirmed", "pending_payment")),
            or_(
                Booking.status == "confirmed",
                (Booking.status == "pending_payment") & (Booking.hold_expires_at > now),
            ),
            Booking.start_at >= now - timedelta(days=30),
        ]
        rows = self.db.execute(
            select(Booking, BookingOrder, Calendar)
            .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
            .join(Calendar, Calendar.id == Booking.calendar_id)
            .where(*conditions)
            .order_by(Booking.start_at, Booking.id)
            .limit(200)
        )
        result: list[NotificationItem] = []
        for booking, order, calendar in rows:
            readiness = readiness_for_booking(self.db, booking)
            if readiness.ready:
                continue
            roles = [
                str(role)
                for role in (calendar.required_staff_roles or ["Captain"])
                if str(role).strip()
            ]
            assignments = list(
                self.db.scalars(
                    select(StaffAssignment).where(
                        StaffAssignment.operator_id == self.operator_id,
                        StaffAssignment.calendar_id == calendar.id,
                        StaffAssignment.start_at <= booking.start_at,
                        StaffAssignment.end_at >= booking.end_at,
                    )
                )
            )
            assigned_roles = {str(assignment.role or "").casefold() for assignment in assignments}
            missing_roles = [role for role in roles if role.casefold() not in assigned_roles]
            customer = f"{order.customer_first_name} {order.customer_last_name}".strip()
            result.append(
                NotificationItem(
                    id=f"booking-staff:{booking.id}",
                    type="booking_staff",
                    title=f"Assign staff to {customer or 'booking'}",
                    description=(
                        readiness.reason
                        or "Assign the required staff before this booking is fully configured."
                    ),
                    action_label="Assign staff",
                    calendar_id=calendar.id,
                    calendar_name=booking.calendar_name_snapshot or calendar.name,
                    booking_id=booking.id,
                    customer_name=customer,
                    start_at=booking.start_at,
                    end_at=booking.end_at,
                    required_roles=roles,
                    missing_roles=missing_roles,
                )
            )
        return result

    @staticmethod
    def _sort_key(item: NotificationItem) -> tuple[int, datetime, str]:
        priority = {"booking_staff": 0, "calendar_availability": 1, "calendar_resources": 2}
        return priority[item.type], item.start_at or datetime.max.replace(tzinfo=UTC), item.id
