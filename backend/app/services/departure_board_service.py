from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.entities import (
    Booking,
    BookingOrder,
    BookingResource,
    Calendar,
    CalendarBlock,
    CalendarCategory,
    CalendarRate,
    CalendarRateResource,
    CalendarResource,
    Operator,
    Payment,
    Resource,
    Staff,
    StaffAssignment,
)
from app.schemas.pwa import (
    PWADeparture,
    PWADepartureBooking,
    PWADepartureResource,
    PWADeparturesResponse,
    PWADepartureStaff,
)
from app.services.availability_service import AvailabilityService
from app.services.capacity import CapacityInterval, reserved_for_interval
from app.services.pwa_workspace_service import local_day_bounds

INACTIVE_BOOKING_STATUSES = frozenset({"cancelled", "failed"})


class DepartureBoardService:
    """Read-only departure board for one operator-local day.

    Every departure an active calendar offers is listed, booked or not, using
    the same candidate generation as public booking so staff see exactly what
    customers can buy. Inventory is reported per resource type because
    resources are shared across calendars and are not interchangeable units.
    """

    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id
        self.availability = AvailabilityService(db)

    def local_date(self, instant: datetime) -> date:
        """The operator-local calendar day an instant falls on."""

        operator = self.db.get(Operator, self.operator_id)
        time_zone = ((operator.time_zone if operator else None) or "UTC").strip() or "UTC"
        try:
            return instant.astimezone(ZoneInfo(time_zone)).date()
        except ZoneInfoNotFoundError:
            return instant.astimezone(UTC).date()

    def day(self, target_date: date, *, calendar_id: uuid.UUID | None = None) -> PWADeparturesResponse:
        operator = self.db.get(Operator, self.operator_id)
        if operator is None:
            raise NotFoundError("Operator not found")
        time_zone = (operator.time_zone or "UTC").strip() or "UTC"
        day_start, day_end = local_day_bounds(target_date, time_zone)

        calendar_conditions = [Calendar.operator_id == self.operator_id]
        if calendar_id:
            calendar_conditions.append(Calendar.id == calendar_id)
        calendars = {
            calendar.id: (calendar, color)
            for calendar, color in self.db.execute(
                select(Calendar, CalendarCategory.display_color)
                .outerjoin(CalendarCategory, CalendarCategory.id == Calendar.calendar_category_id)
                .where(*calendar_conditions)
            )
        }
        offered = {
            cal_id: calendar
            for cal_id, (calendar, _color) in calendars.items()
            if calendar.is_active and calendar.deleted_at is None
        }

        departures: dict[tuple[uuid.UUID, datetime], dict] = {}
        for cal_id, calendar in offered.items():
            source = "pushed" if calendar.availability_mode == "pushed" else "scheduled"
            length = timedelta(minutes=calendar.duration_minutes)
            for start in self.availability._candidate_starts(calendar, operator, target_date):
                start = start.astimezone(UTC)
                departures[(cal_id, start)] = self._departure(cal_id, start, start + length, source)

        booking_rows = self.db.execute(
            select(Booking, BookingOrder, Payment)
            .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
            .outerjoin(Payment, Payment.booking_order_id == BookingOrder.id)
            .where(
                Booking.operator_id == self.operator_id,
                Booking.calendar_id.in_(list(calendars)),
                Booking.start_at >= day_start,
                Booking.start_at < day_end,
            )
            .order_by(Booking.start_at, BookingOrder.customer_last_name, Booking.id)
        ).all()
        for booking, order, payment in booking_rows:
            key = (booking.calendar_id, booking.start_at.astimezone(UTC))
            departure = departures.get(key)
            if departure is None:
                # A booking at a time the calendar no longer offers (hours
                # changed, calendar paused) must still appear on the board.
                departure = departures[key] = self._departure(
                    booking.calendar_id, key[1], booking.end_at.astimezone(UTC), "unscheduled"
                )
            departure["end_at"] = max(departure["end_at"], booking.end_at.astimezone(UTC))
            departure["bookings"].append(
                PWADepartureBooking(
                    id=booking.id,
                    public_reference=order.public_reference,
                    lead_name=f"{order.customer_first_name} {order.customer_last_name}".strip(),
                    status=booking.status,
                    payment_status=payment.status if payment else None,
                    payment_method=payment.payment_method if payment else None,
                    units=booking.units,
                )
            )
            if booking.status not in INACTIVE_BOOKING_STATUSES:
                departure["booked_units"] += booking.units

        if not departures:
            return PWADeparturesResponse(date=target_date, time_zone=time_zone, departures=[])

        range_start = min(item["start_at"] for item in departures.values())
        range_end = max(item["end_at"] for item in departures.values())
        resources_by_calendar = self._resources_by_calendar(list(calendars))
        confirmed, held = self._reservations(
            {resource.id for items in resources_by_calendar.values() for resource in items},
            range_start,
            range_end,
        )
        blocks = defaultdict(list)
        for block_calendar, block_start, block_end in self.db.execute(
            select(CalendarBlock.calendar_id, CalendarBlock.start_at, CalendarBlock.end_at).where(
                CalendarBlock.calendar_id.in_(list(calendars)),
                CalendarBlock.start_at < range_end,
                CalendarBlock.end_at > range_start,
            )
        ):
            blocks[block_calendar].append((block_start, block_end))
        assignments = defaultdict(list)
        for assignment, staff_name in self.db.execute(
            select(StaffAssignment, Staff.name)
            .join(Staff, Staff.id == StaffAssignment.staff_id)
            .where(
                StaffAssignment.operator_id == self.operator_id,
                StaffAssignment.calendar_id.in_(list(calendars)),
                StaffAssignment.start_at < range_end,
                StaffAssignment.end_at > range_start,
            )
            .order_by(Staff.name)
        ):
            assignments[assignment.calendar_id].append((assignment, staff_name))

        result: list[PWADeparture] = []
        for (cal_id, start_at), item in sorted(
            departures.items(), key=lambda pair: (pair[0][1], calendars[pair[0][0]][0].name.lower())
        ):
            calendar, color = calendars[cal_id]
            end_at = item["end_at"]
            inventory = []
            for resource in resources_by_calendar.get(cal_id, []):
                usable = resource.is_active and resource.deleted_at is None
                total = resource.quantity if usable else 0
                confirmed_units = reserved_for_interval(confirmed.get(resource.id, []), start_at, end_at)
                # Peak usage of both kinds together is what blocks a sale.
                combined = reserved_for_interval(
                    confirmed.get(resource.id, []) + held.get(resource.id, []), start_at, end_at
                )
                inventory.append(
                    PWADepartureResource(
                        resource_id=resource.id,
                        name=resource.name,
                        total=total,
                        confirmed=confirmed_units,
                        held=max(0, combined - confirmed_units),
                        remaining=max(0, total - combined),
                    )
                )
            result.append(
                PWADeparture(
                    calendar_id=cal_id,
                    calendar_name=calendar.name,
                    category_color=color,
                    start_at=start_at,
                    end_at=end_at,
                    source=item["source"],
                    blocked=any(
                        block_start < end_at and block_end > start_at
                        for block_start, block_end in blocks.get(cal_id, [])
                    ),
                    resources=inventory,
                    bookings=item["bookings"],
                    staff=[
                        PWADepartureStaff(
                            assignment_id=assignment.id,
                            staff_id=assignment.staff_id,
                            staff_name=staff_name,
                            role=assignment.role,
                        )
                        for assignment, staff_name in assignments.get(cal_id, [])
                        # Assigned to this departure, or on shift for all of it;
                        # a partial overlap belongs to a neighbouring departure.
                        if assignment.start_at == start_at
                        or (assignment.start_at <= start_at and assignment.end_at >= end_at)
                    ],
                    booked_units=item["booked_units"],
                )
            )
        return PWADeparturesResponse(date=target_date, time_zone=time_zone, departures=result)

    @staticmethod
    def _departure(cal_id: uuid.UUID, start_at: datetime, end_at: datetime, source: str) -> dict:
        return {
            "calendar_id": cal_id,
            "start_at": start_at,
            "end_at": end_at,
            "source": source,
            "bookings": [],
            "booked_units": 0,
        }

    def _resources_by_calendar(self, calendar_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Resource]]:
        """Resources a calendar sells: legacy calendar mappings plus active rate mappings."""

        found: dict[uuid.UUID, dict[uuid.UUID, Resource]] = defaultdict(dict)
        for cal_id, resource in self.db.execute(
            select(CalendarResource.calendar_id, Resource)
            .join(Resource, Resource.id == CalendarResource.resource_id)
            .where(CalendarResource.calendar_id.in_(calendar_ids))
        ):
            found[cal_id][resource.id] = resource
        for cal_id, resource in self.db.execute(
            select(CalendarRate.calendar_id, Resource)
            .join(CalendarRateResource, CalendarRateResource.rate_id == CalendarRate.id)
            .join(Resource, Resource.id == CalendarRateResource.resource_id)
            .where(
                CalendarRate.calendar_id.in_(calendar_ids),
                CalendarRate.deleted_at.is_(None),
                CalendarRate.is_active.is_(True),
            )
        ):
            found[cal_id][resource.id] = resource
        return {
            cal_id: sorted(items.values(), key=lambda resource: resource.name.lower())
            for cal_id, items in found.items()
        }

    def _reservations(
        self, resource_ids: set[uuid.UUID], range_start: datetime, range_end: datetime
    ) -> tuple[dict[uuid.UUID, list[CapacityInterval]], dict[uuid.UUID, list[CapacityInterval]]]:
        """Reservations across every calendar sharing these resources, split by kind."""

        confirmed: dict[uuid.UUID, list[CapacityInterval]] = defaultdict(list)
        held: dict[uuid.UUID, list[CapacityInterval]] = defaultdict(list)
        if not resource_ids:
            return confirmed, held
        now = datetime.now(UTC)
        rows = self.db.execute(
            select(
                BookingResource.resource_id,
                Booking.status,
                Booking.start_at,
                Booking.end_at,
                BookingResource.quantity,
            )
            .join(Booking, Booking.id == BookingResource.booking_id)
            .where(
                BookingResource.resource_id.in_(list(resource_ids)),
                Booking.start_at < range_end,
                Booking.end_at > range_start,
                or_(
                    Booking.status == "confirmed",
                    and_(Booking.status == "pending_payment", Booking.hold_expires_at > now),
                ),
            )
        )
        for resource_id, status, start_at, end_at, quantity in rows:
            target = confirmed if status == "confirmed" else held
            target[resource_id].append(CapacityInterval(start_at, end_at, quantity))
        return confirmed, held
