from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.entities import Booking, BookingOrder, Calendar
from app.services.staffing_service import readiness_for_booking


class BookingNotificationService:
    """Tenant-scoped, bounded notifications for actionable booking staffing."""

    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id

    def _conditions(self, now: datetime):
        return [
            Booking.operator_id == self.operator_id,
            Booking.status.in_(("confirmed", "pending_payment")),
            or_(
                Booking.status == "confirmed",
                (Booking.status == "pending_payment") & (Booking.hold_expires_at > now),
            ),
            Booking.start_at >= now - timedelta(days=30),
        ]

    def list(self) -> dict:
        now = datetime.now(UTC)
        conditions = self._conditions(now)
        rows = list(self.db.execute(
            select(Booking, BookingOrder, Calendar)
            .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
            .join(Calendar, Calendar.id == Booking.calendar_id)
            .where(*conditions)
            .order_by(Booking.start_at, Booking.id)
            .limit(200)
        ))
        items = []
        for booking, order, calendar in rows:
            readiness = readiness_for_booking(self.db, booking)
            items.append({
                "booking_id": booking.id,
                "calendar_id": booking.calendar_id,
                "calendar_name": booking.calendar_name_snapshot or calendar.name,
                "customer_name": f"{order.customer_first_name} {order.customer_last_name}",
                "start_at": booking.start_at,
                "end_at": booking.end_at,
                "units": booking.units,
                "status": booking.status,
                "created_at": booking.created_at,
                "assignment_status": "completed" if readiness.ready else "pending",
                "captain_name": readiness.captain_name,
                "reason": None if readiness.ready else readiness.reason,
            })
        pending_count = sum(
            not readiness_for_booking(self.db, booking).ready
            for booking in self.db.scalars(select(Booking).where(*conditions))
        )
        return {"items": items, "pending_count": pending_count}
