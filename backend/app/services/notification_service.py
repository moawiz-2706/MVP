from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Booking,
    BookingOrder,
    Calendar,
    CalendarDateHour,
    CalendarHour,
    CalendarPushedSlot,
    CalendarResource,
    GHLSyncRun,
)
from app.schemas.notifications import NotificationItem, NotificationsResponse


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
        items.extend(self._ghl_sync_items())
        items.sort(key=self._sort_key)
        return NotificationsResponse(
            items=items,
            pending_count=len(items),
            generated_at=now,
        )

    def _ghl_sync_items(self) -> list[NotificationItem]:
        runs = list(
            self.db.scalars(
                select(GHLSyncRun)
                .where(
                    GHLSyncRun.operator_id == self.operator_id,
                    GHLSyncRun.status.in_(("failed", "partial", "manual_review")),
                    GHLSyncRun.resolved_at.is_(None),
                )
                .order_by(GHLSyncRun.created_at.desc())
                .limit(100)
            )
        )
        result: list[NotificationItem] = []
        for run in runs:
            if run.booking_order_id is None:
                continue
            row = self.db.execute(
                select(Booking, BookingOrder, Calendar)
                .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
                .join(Calendar, Calendar.id == Booking.calendar_id)
                .where(
                    Booking.booking_order_id == run.booking_order_id,
                    Booking.operator_id == self.operator_id,
                )
                .order_by(Booking.start_at, Booking.id)
                .limit(1)
            ).one_or_none()
            if row is None:
                continue
            booking, order, calendar = row
            customer = f"{order.customer_first_name} {order.customer_last_name}".strip()
            result.append(
                NotificationItem(
                    id=f"ghl-sync:{run.id}",
                    type="ghl_sync_failed",
                    title=f"Resync {customer or 'booking'} to HighLevel",
                    description=(
                        f"HighLevel synchronization failed after {run.attempt_count} attempt(s): "
                        f"{run.last_error or 'Unknown provider error'}."
                    ),
                    action_label="Resync to GHL",
                    calendar_id=calendar.id,
                    calendar_name=booking.calendar_name_snapshot or calendar.name,
                    booking_id=booking.id,
                    customer_name=customer,
                    start_at=booking.start_at,
                    end_at=booking.end_at,
                    order_id=order.id,
                    sync_run_id=run.id,
                    sync_attempts=run.attempt_count,
                    error_code=run.last_error_code,
                )
            )
        return result

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

    @staticmethod
    def _sort_key(item: NotificationItem) -> tuple[int, datetime, str]:
        priority = {
            "ghl_sync_failed": 0,
            "calendar_availability": 2,
            "calendar_resources": 3,
        }
        return priority[item.type], item.start_at or datetime.max.replace(tzinfo=UTC), item.id
