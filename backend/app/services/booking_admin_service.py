# The class defines a method named `list`; without deferred annotations a later
# `-> list[dict]` would resolve to that method at import time on Python 3.12.
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, DomainError, NotFoundError
from app.models.entities import (
    AppUser,
    Booking,
    BookingNote,
    BookingOrder,
    BookingResource,
    Calendar,
    CalendarCategory,
    CalendarPushedSlot,
    CalendarResource,
    OutboxJob,
    Payment,
    Resource,
    Staff,
    StaffAssignment,
)
from app.schemas.booking import BookingUpdate
from app.services.availability_service import AvailabilityService
from app.services.waiver_service import WaiverService


class BookingAdminService:
    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id

    def list(
        self,
        range_start: datetime,
        range_end: datetime,
        *,
        calendar_id: uuid.UUID | None = None,
        category_id: uuid.UUID | None = None,
        booking_status: str | None = None,
        search: str | None = None,
    ) -> list[dict]:
        if range_start.tzinfo is None or range_end.tzinfo is None or range_start >= range_end:
            raise ValueError("A valid timezone-aware range is required")
        if range_end - range_start > timedelta(days=93):
            raise ValueError("Booking query range cannot exceed 93 days")
        conditions = [
            Booking.operator_id == self.operator_id,
            Booking.start_at < range_end,
            Booking.end_at > range_start,
        ]
        if calendar_id:
            conditions.append(Booking.calendar_id == calendar_id)
        if category_id:
            conditions.append(Calendar.calendar_category_id == category_id)
        if booking_status:
            conditions.append(Booking.status == booking_status)
        if search:
            needle = f"%{search.strip()}%"
            conditions.append(
                or_(
                    BookingOrder.customer_first_name.ilike(needle),
                    BookingOrder.customer_last_name.ilike(needle),
                    BookingOrder.customer_email.ilike(needle),
                    BookingOrder.public_reference.ilike(needle),
                )
            )
        rows = self.db.execute(
            select(Booking, BookingOrder, CalendarCategory)
            .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
            .join(Calendar, Calendar.id == Booking.calendar_id)
            .outerjoin(CalendarCategory, CalendarCategory.id == Calendar.calendar_category_id)
            .where(*conditions)
            .order_by(Booking.start_at, Booking.id)
        )
        return [self._list_dict(booking, order, category) for booking, order, category in rows]

    def slots(
        self,
        range_start: datetime,
        range_end: datetime,
        *,
        calendar_id: uuid.UUID | None = None,
        category_id: uuid.UUID | None = None,
        search: str | None = None,
    ) -> list[dict]:
        """Dashboard feed: one entry per start instant, split by calendar.

        A (start, calendar) pair appears when it has bookings (any status), staff
        assigned, or — for pushed-mode calendars — an offered start, so staff can
        be scheduled before anyone books. A search narrows to pairs with a
        matching booking.
        """
        bookings = self.list(
            range_start, range_end, calendar_id=calendar_id, category_id=category_id, search=search
        )
        calendar_conditions = [Calendar.operator_id == self.operator_id]
        if calendar_id:
            calendar_conditions.append(Calendar.id == calendar_id)
        if category_id:
            calendar_conditions.append(Calendar.calendar_category_id == category_id)
        calendars = {
            calendar.id: (calendar, color)
            for calendar, color in self.db.execute(
                select(Calendar, CalendarCategory.display_color)
                .outerjoin(CalendarCategory, CalendarCategory.id == Calendar.calendar_category_id)
                .where(*calendar_conditions)
            )
        }

        entries: dict[tuple[datetime, uuid.UUID], dict] = {}

        def entry(start_at: datetime, cal_id: uuid.UUID, end_at: datetime, name: str | None = None) -> dict:
            current = entries.get((start_at, cal_id))
            if current is None:
                calendar, color = calendars.get(cal_id, (None, None))
                current = entries[(start_at, cal_id)] = {
                    "calendar_id": cal_id,
                    "calendar_name": name or (calendar.name if calendar else "Calendar"),
                    "category_color": color,
                    "end_at": end_at,
                    "pushed": False,
                    "bookings": [],
                    "staff": [],
                }
            else:
                current["end_at"] = max(current["end_at"], end_at)
            return current

        for booking in bookings:
            entry(
                booking["start_at"], booking["calendar_id"], booking["end_at"], booking["calendar_name"]
            )["bookings"].append(booking)

        if calendars:
            assignments = self.db.execute(
                select(StaffAssignment, Staff.name)
                .join(Staff, Staff.id == StaffAssignment.staff_id)
                .where(
                    StaffAssignment.operator_id == self.operator_id,
                    StaffAssignment.calendar_id.in_(list(calendars)),
                    StaffAssignment.start_at < range_end,
                    StaffAssignment.end_at > range_start,
                )
                .order_by(Staff.name)
            )
            for assignment, staff_name in assignments:
                key = (assignment.start_at, assignment.calendar_id)
                if search and key not in entries:
                    continue
                entry(assignment.start_at, assignment.calendar_id, assignment.end_at)["staff"].append(
                    {
                        "id": assignment.id,
                        "staff_id": assignment.staff_id,
                        "staff_name": staff_name,
                        "role": assignment.role,
                    }
                )

            pushed_calendars = {
                cal_id: calendar
                for cal_id, (calendar, _) in calendars.items()
                if calendar.availability_mode == "pushed" and calendar.deleted_at is None
            }
            if pushed_calendars:
                pushed = self.db.execute(
                    select(CalendarPushedSlot.calendar_id, CalendarPushedSlot.start_at).where(
                        CalendarPushedSlot.calendar_id.in_(list(pushed_calendars)),
                        CalendarPushedSlot.start_at >= range_start,
                        CalendarPushedSlot.start_at < range_end,
                    )
                )
                for cal_id, start_at in pushed:
                    if search and (start_at, cal_id) not in entries:
                        continue
                    length = timedelta(minutes=pushed_calendars[cal_id].duration_minutes)
                    entry(start_at, cal_id, start_at + length)["pushed"] = True

        by_start: dict[datetime, list[dict]] = defaultdict(list)
        for (start_at, _), value in entries.items():
            by_start[start_at].append(value)
        return [
            {"start_at": start_at, "calendars": sorted(group, key=lambda e: e["calendar_name"].lower())}
            for start_at, group in sorted(by_start.items())
        ]

    @staticmethod
    def _list_dict(booking, order, category) -> dict:
        return {
            "id": booking.id,
            "booking_order_id": order.id,
            "public_reference": order.public_reference,
            "calendar_id": booking.calendar_id,
            "calendar_name": booking.calendar_name_snapshot,
            "category_id": category.id if category else None,
            "category_name": category.name if category else None,
            "category_color": category.display_color if category else None,
            "customer_name": f"{order.customer_first_name} {order.customer_last_name}",
            "customer_email": order.customer_email,
            "start_at": booking.start_at,
            "end_at": booking.end_at,
            "units": booking.units,
            "status": booking.status,
        }

    def detail(self, booking_id: uuid.UUID) -> dict:
        row = self.db.execute(
            select(Booking, BookingOrder, Payment, CalendarCategory)
            .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
            .join(Payment, Payment.booking_order_id == BookingOrder.id)
            .join(Calendar, Calendar.id == Booking.calendar_id)
            .outerjoin(CalendarCategory, CalendarCategory.id == Calendar.calendar_category_id)
            .where(Booking.id == booking_id, Booking.operator_id == self.operator_id)
        ).one_or_none()
        if row is None:
            raise NotFoundError("Booking not found")
        booking, order, payment, category = row
        resources = self.db.execute(
            select(BookingResource.resource_id, Resource.name, BookingResource.quantity)
            .join(Resource, Resource.id == BookingResource.resource_id)
            .where(BookingResource.booking_id == booking.id)
            .order_by(Resource.name)
        )
        return {
            **self._list_dict(booking, order, category),
            "customer_phone": order.customer_phone,
            "location_name": booking.departure_location_name_snapshot,
            "location_address": booking.departure_location_address_snapshot,
            "payment_status": payment.status,
            "subtotal_minor": order.subtotal_minor,
            "platform_fee_and_taxes_minor": order.platform_fee_and_taxes_minor,
            "customer_total_minor": order.customer_total_minor,
            "ghl_contact_sync_status": order.ghl_contact_sync_status,
            "ghl_confirmation_email_status": order.ghl_confirmation_email_status,
            "resources": [
                {"resource_id": resource_id, "name": name, "quantity": quantity}
                for resource_id, name, quantity in resources
            ],
            "created_at": booking.created_at,
            "waiver": WaiverService(self.db).summary(booking),
            "notes": self._notes(booking.id),
        }

    def cancel(self, booking_id: uuid.UUID) -> None:
        booking = self.db.scalar(
            select(Booking)
            .where(Booking.id == booking_id, Booking.operator_id == self.operator_id)
            .with_for_update()
        )
        if booking is None:
            raise NotFoundError("Booking not found")
        if booking.status in {"cancelled", "failed"}:
            return
        booking.status = "cancelled"
        booking.hold_expires_at = None
        remaining = self.db.scalar(
            select(func.count(Booking.id)).where(
                Booking.booking_order_id == booking.booking_order_id,
                Booking.id != booking.id,
                Booking.status.not_in(["cancelled", "failed"]),
            )
        )
        if not remaining:
            order = self.db.get(BookingOrder, booking.booking_order_id)
            if order:
                order.status = "cancelled"
        self.db.commit()

    def update(self, booking_id: uuid.UUID, data: BookingUpdate) -> dict:
        booking = self.db.scalar(
            select(Booking)
            .where(Booking.id == booking_id, Booking.operator_id == self.operator_id)
            .with_for_update()
        )
        if booking is None:
            raise NotFoundError("Booking not found")
        payment = self.db.scalar(
            select(Payment).where(Payment.booking_order_id == booking.booking_order_id)
        )
        if payment and payment.customer_total_minor > 0 and payment.status == "succeeded":
            raise ConflictError("Paid booking time or quantity changes require an adjustment workflow")
        start_at = data.start_at or booking.start_at
        units = data.units or booking.units
        calendar = self.db.scalar(
            select(Calendar).where(
                Calendar.id == booking.calendar_id, Calendar.operator_id == self.operator_id
            )
        )
        if calendar is None:
            raise NotFoundError("Calendar not found")
        resource_ids = set(
            self.db.scalars(
                select(BookingResource.resource_id).where(BookingResource.booking_id == booking.id)
            )
        )
        resource_ids.update(
            self.db.scalars(
                select(CalendarResource.resource_id).where(
                    CalendarResource.calendar_id == calendar.id
                )
            )
        )
        if resource_ids:
            list(
                self.db.scalars(
                    select(Resource)
                    .where(Resource.id.in_(sorted(resource_ids)))
                    .order_by(Resource.id)
                    .with_for_update()
                )
            )
        result = AvailabilityService(self.db).check(
            calendar.id,
            start_at,
            units,
            operator_id=self.operator_id,
            exclude_booking_ids={booking.id},
        )
        if not result.available:
            raise ConflictError(result.reason or "Updated booking is unavailable")
        booking.start_at = result.start_at
        booking.end_at = result.end_at
        booking.units = units
        for existing in list(
            self.db.scalars(
                select(BookingResource).where(BookingResource.booking_id == booking.id)
            )
        ):
            self.db.delete(existing)
        for mapping in self.db.scalars(
            select(CalendarResource).where(CalendarResource.calendar_id == calendar.id)
        ):
            self.db.add(
                BookingResource(
                    booking_id=booking.id,
                    resource_id=mapping.resource_id,
                    quantity=units * mapping.default_quantity_per_unit,
                )
            )
        self.db.commit()
        return self.detail(booking.id)

    def _booking(self, booking_id: uuid.UUID) -> Booking:
        booking = self.db.scalar(
            select(Booking).where(Booking.id == booking_id, Booking.operator_id == self.operator_id)
        )
        if booking is None:
            raise NotFoundError("Booking not found")
        return booking

    @staticmethod
    def _note_dict(note: BookingNote) -> dict:
        return {
            "id": note.id,
            "author_user_id": note.author_user_id,
            "author_name": note.author_name,
            "body": note.body,
            "created_at": note.created_at,
        }

    def _notes(self, booking_id: uuid.UUID) -> list[dict]:
        return [
            self._note_dict(note)
            for note in self.db.scalars(
                select(BookingNote)
                .where(BookingNote.booking_id == booking_id)
                .order_by(BookingNote.created_at, BookingNote.id)
            )
        ]

    def add_note(self, booking_id: uuid.UUID, body: str, author_user_id: uuid.UUID) -> dict:
        booking = self._booking(booking_id)
        author = self.db.get(AppUser, author_user_id)
        note = BookingNote(
            operator_id=self.operator_id,
            booking_id=booking.id,
            author_user_id=author.id if author else None,
            # Snapshot the name so the note still reads correctly if the user changes.
            author_name=(author.name or author.email) if author else None,
            body=body,
        )
        self.db.add(note)
        self.db.commit()
        self.db.refresh(note)
        return self._note_dict(note)

    def delete_note(
        self, booking_id: uuid.UUID, note_id: uuid.UUID, *, user_id: uuid.UUID, is_admin: bool
    ) -> None:
        note = self.db.scalar(
            select(BookingNote).where(
                BookingNote.id == note_id,
                BookingNote.booking_id == booking_id,
                BookingNote.operator_id == self.operator_id,
            )
        )
        if note is None:
            raise NotFoundError("Note not found")
        if note.author_user_id != user_id and not is_admin:
            raise DomainError("You can only delete your own notes", status_code=403, code="forbidden")
        self.db.delete(note)
        self.db.commit()

    def retry_ghl(self, order_id: uuid.UUID) -> None:
        order = self.db.scalar(
            select(BookingOrder).where(
                BookingOrder.id == order_id, BookingOrder.operator_id == self.operator_id
            )
        )
        if order is None:
            raise NotFoundError("Order not found")
        for job in self.db.scalars(
            select(OutboxJob).where(
                OutboxJob.booking_order_id == order_id,
                OutboxJob.job_type.in_(["ghl_upsert_contact", "ghl_send_confirmation_email"]),
            )
        ):
            job.status = "pending"
            job.next_attempt_at = None
            job.last_error = None
        order.ghl_contact_sync_status = "pending"
        order.ghl_confirmation_email_status = "pending"
        self.db.commit()

