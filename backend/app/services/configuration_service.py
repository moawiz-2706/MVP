import logging
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any, TypeVar

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import (
    Booking,
    BookingFinancialAllocation,
    BookingNote,
    BookingResource,
    BookingWaiver,
    Calendar,
    CalendarBlock,
    CalendarCategory,
    CalendarDateHour,
    CalendarHour,
    CalendarPushedSlot,
    CalendarResource,
    DepartureLocation,
    GHLAppointmentMapping,
    GHLCalendarMapping,
    Operator,
    OutboxJob,
    Resource,
    StaffAssignment,
)
from app.schemas.configuration import (
    CalendarBlocksReplace,
    CalendarBlockWrite,
    CalendarCreate,
    CalendarDateHoursReplace,
    CalendarHoursReplace,
    CalendarResourcesReplace,
    CalendarUpdate,
    CategoryCreate,
    CategoryUpdate,
    LocationCreate,
    LocationUpdate,
    PushedSlotsCreate,
    ResourceCreate,
    ResourceUpdate,
)
from app.utils.timezone import local_datetime, require_timezone, wall_time_exists
from app.services.outbox_service import OutboxService

ModelT = TypeVar("ModelT")

logger = logging.getLogger("passport.configuration")


def _apply(model: Any, values: dict[str, Any]) -> None:
    for key, value in values.items():
        setattr(model, key, value)


class ConfigurationService:
    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id

    def _owned(self, model: type[ModelT], entity_id: uuid.UUID, *, active: bool = False) -> ModelT:
        conditions = [model.id == entity_id, model.operator_id == self.operator_id]  # type: ignore[attr-defined]
        if active:
            conditions.extend([model.deleted_at.is_(None), model.is_active.is_(True)])  # type: ignore[attr-defined]
        entity = self.db.scalar(select(model).where(*conditions))
        if entity is None:
            raise NotFoundError()
        return entity

    def list_locations(self) -> list[dict[str, Any]]:
        count = (
            select(func.count(Calendar.id))
            .where(
                Calendar.departure_location_id == DepartureLocation.id,
                Calendar.deleted_at.is_(None),
            )
            .correlate(DepartureLocation)
            .scalar_subquery()
        )
        rows = self.db.execute(
            select(DepartureLocation, count.label("calendars_count"))
            .where(
                DepartureLocation.operator_id == self.operator_id,
                DepartureLocation.deleted_at.is_(None),
            )
            .order_by(DepartureLocation.name)
        )
        return [{**entity.__dict__, "calendars_count": total} for entity, total in rows]

    def create_location(self, data: LocationCreate) -> DepartureLocation:
        entity = DepartureLocation(operator_id=self.operator_id, **data.model_dump())
        self.db.add(entity)
        self.db.commit()
        self.db.refresh(entity)
        return entity

    def get_location(self, entity_id: uuid.UUID) -> DepartureLocation:
        return self._owned(DepartureLocation, entity_id)

    def update_location(self, entity_id: uuid.UUID, data: LocationUpdate) -> DepartureLocation:
        entity = self.get_location(entity_id)
        calendars = list(
            self.db.scalars(
                select(Calendar).where(
                    Calendar.operator_id == self.operator_id,
                    Calendar.departure_location_id == entity_id,
                    Calendar.deleted_at.is_(None),
                )
            )
        )
        _apply(entity, data.model_dump(exclude_unset=True))
        self.db.commit()
        self.db.refresh(entity)
        for calendar in calendars:
            self._queue_ghl_calendar_sync(calendar)
        return entity

    def delete_location(self, entity_id: uuid.UUID) -> None:
        entity = self.get_location(entity_id)
        now = datetime.now(UTC)
        entity.deleted_at = now
        entity.is_active = False
        calendars = list(
            self.db.scalars(
                select(Calendar).where(
                    Calendar.operator_id == self.operator_id,
                    Calendar.departure_location_id == entity_id,
                    Calendar.deleted_at.is_(None),
                )
            )
        )
        self.db.execute(
            update(Calendar)
            .where(
                Calendar.operator_id == self.operator_id,
                Calendar.departure_location_id == entity_id,
            )
            .values(departure_location_id=None)
        )
        self.db.commit()
        for calendar in calendars:
            self._queue_ghl_calendar_sync(calendar)

    def list_resources(self) -> list[dict[str, Any]]:
        count = (
            select(func.count(CalendarResource.calendar_id))
            .join(Calendar, Calendar.id == CalendarResource.calendar_id)
            .where(
                CalendarResource.resource_id == Resource.id,
                Calendar.deleted_at.is_(None),
            )
            .correlate(Resource)
            .scalar_subquery()
        )
        rows = self.db.execute(
            select(Resource, count.label("calendars_count"))
            .where(Resource.operator_id == self.operator_id, Resource.deleted_at.is_(None))
            .order_by(Resource.name)
        )
        return [{**entity.__dict__, "calendars_count": total} for entity, total in rows]

    def create_resource(self, data: ResourceCreate) -> Resource:
        entity = Resource(operator_id=self.operator_id, **data.model_dump())
        self.db.add(entity)
        self.db.commit()
        self.db.refresh(entity)
        return entity

    def get_resource(self, entity_id: uuid.UUID) -> Resource:
        return self._owned(Resource, entity_id)

    def peak_future_resource_usage(self, resource_id: uuid.UUID) -> int:
        now = datetime.now(UTC)
        rows = self.db.execute(
            select(Booking.start_at, Booking.end_at, BookingResource.quantity)
            .join(BookingResource, BookingResource.booking_id == Booking.id)
            .where(
                Booking.operator_id == self.operator_id,
                BookingResource.resource_id == resource_id,
                Booking.end_at > now,
                or_(
                    Booking.status == "confirmed",
                    (Booking.status == "pending_payment") & (Booking.hold_expires_at > now),
                ),
            )
        ).all()
        events: list[tuple[datetime, int, int]] = []
        for start_at, end_at, quantity in rows:
            events.append((start_at, 1, quantity))
            events.append((end_at, 0, -quantity))  # end first: touching intervals do not overlap
        current = peak = 0
        for _, _, delta in sorted(events, key=lambda item: (item[0], item[1])):
            current += delta
            peak = max(peak, current)
        return peak

    def update_resource(self, entity_id: uuid.UUID, data: ResourceUpdate) -> Resource:
        entity = self.get_resource(entity_id)
        values = data.model_dump(exclude_unset=True)
        if "quantity" in values and values["quantity"] < entity.quantity:
            peak = self.peak_future_resource_usage(entity_id)
            if values["quantity"] < peak:
                raise ConflictError(
                    f"Quantity cannot be reduced below peak reserved usage ({peak})",
                    details={"peak_reserved": peak},
                )
        _apply(entity, values)
        self.db.commit()
        self.db.refresh(entity)
        return entity

    def delete_resource(self, entity_id: uuid.UUID) -> None:
        entity = self.get_resource(entity_id)
        entity.deleted_at = datetime.now(UTC)
        entity.is_active = False
        self.db.execute(delete(CalendarResource).where(CalendarResource.resource_id == entity_id))
        self.db.commit()

    def list_categories(self) -> list[dict[str, Any]]:
        count = (
            select(func.count(Calendar.id))
            .where(
                Calendar.calendar_category_id == CalendarCategory.id,
                Calendar.deleted_at.is_(None),
            )
            .correlate(CalendarCategory)
            .scalar_subquery()
        )
        rows = self.db.execute(
            select(CalendarCategory, count.label("calendars_count"))
            .where(
                CalendarCategory.operator_id == self.operator_id,
                CalendarCategory.deleted_at.is_(None),
            )
            .order_by(CalendarCategory.sort_order, CalendarCategory.name)
        )
        return [{**entity.__dict__, "calendars_count": total} for entity, total in rows]

    def create_category(self, data: CategoryCreate) -> CalendarCategory:
        entity = CalendarCategory(operator_id=self.operator_id, **data.model_dump())
        self.db.add(entity)
        self._commit_category()
        self.db.refresh(entity)
        return entity

    def get_category(self, entity_id: uuid.UUID) -> CalendarCategory:
        return self._owned(CalendarCategory, entity_id)

    def update_category(self, entity_id: uuid.UUID, data: CategoryUpdate) -> CalendarCategory:
        entity = self.get_category(entity_id)
        _apply(entity, data.model_dump(exclude_unset=True))
        self._commit_category()
        self.db.refresh(entity)
        return entity

    def _commit_category(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("A category with that name or slug already exists") from exc

    def delete_category(self, entity_id: uuid.UUID) -> None:
        entity = self.get_category(entity_id)
        now = datetime.now(UTC)
        self.db.execute(
            update(Calendar)
            .where(
                Calendar.operator_id == self.operator_id,
                Calendar.calendar_category_id == entity_id,
                Calendar.deleted_at.is_(None),
            )
            .values(deleted_at=now, is_active=False, public_booking_enabled=False)
        )
        entity.deleted_at = now
        entity.is_active = False
        self.db.commit()

    def _validate_calendar_refs(
        self, category_id: uuid.UUID | None, location_id: uuid.UUID | None
    ) -> None:
        if category_id is not None:
            self._owned(CalendarCategory, category_id, active=True)
        if location_id is not None:
            self._owned(DepartureLocation, location_id, active=True)

    def list_calendars(
        self,
        category_id: uuid.UUID | None = None,
        location_id: uuid.UUID | None = None,
        is_active: bool | None = None,
    ) -> list[Calendar]:
        conditions = [Calendar.operator_id == self.operator_id, Calendar.deleted_at.is_(None)]
        if category_id:
            conditions.append(Calendar.calendar_category_id == category_id)
        if location_id:
            conditions.append(Calendar.departure_location_id == location_id)
        if is_active is not None:
            conditions.append(Calendar.is_active.is_(is_active))
        return list(self.db.scalars(select(Calendar).where(*conditions).order_by(Calendar.name)))

    def create_calendar(self, data: CalendarCreate) -> Calendar:
        self._validate_calendar_refs(data.calendar_category_id, data.departure_location_id)
        entity = Calendar(operator_id=self.operator_id, **data.model_dump())
        self.db.add(entity)
        self._commit_calendar()
        self.db.refresh(entity)
        self._queue_ghl_calendar_sync(entity)
        return entity

    def get_calendar(self, entity_id: uuid.UUID, *, active: bool = False) -> Calendar:
        return self._owned(Calendar, entity_id, active=True)

    def _commit_calendar(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("A calendar with that slug already exists") from exc

    def update_calendar(self, entity_id: uuid.UUID, data: CalendarUpdate) -> Calendar:
        entity = self.get_calendar(entity_id)
        values = data.model_dump(exclude_unset=True)
        category_id = values.get("calendar_category_id", entity.calendar_category_id)
        location_id = values.get("departure_location_id", entity.departure_location_id)
        self._validate_calendar_refs(category_id, location_id)
        _apply(entity, values)
        self._commit_calendar()
        self.db.refresh(entity)
        self._queue_ghl_calendar_sync(entity)
        return entity

    def _queue_ghl_calendar_sync(self, calendar: Calendar) -> None:
        if not get_settings().ghl_calendar_sync_enabled:
            return
        mapping = self.db.scalar(
            select(GHLCalendarMapping).where(
                GHLCalendarMapping.operator_id == self.operator_id,
                GHLCalendarMapping.calendar_id == calendar.id,
            )
        )
        if mapping is None:
            mapping = GHLCalendarMapping(
                operator_id=self.operator_id,
                calendar_id=calendar.id,
                desired_revision=1,
                status="pending",
            )
            self.db.add(mapping)
        else:
            mapping.desired_revision += 1
            mapping.status = "pending"
        self.db.add(
            OutboxJob(
                operator_id=self.operator_id,
                job_type="ghl_sync_calendar",
                idempotency_key=f"calendar:{calendar.id}:revision:{mapping.desired_revision}",
                payload={"calendar_id": str(calendar.id)},
                status="pending",
            )
        )
        self.db.commit()
        self._queue_ghl_appointment_sync(calendar.id)

    def _queue_ghl_appointment_sync(self, calendar_id: uuid.UUID) -> None:
        if not get_settings().ghl_calendar_sync_enabled:
            return
        bookings = self.db.scalars(
            select(Booking).where(
                Booking.operator_id == self.operator_id,
                Booking.calendar_id == calendar_id,
                Booking.status.not_in(("cancelled", "failed")),
                Booking.end_at > datetime.now(UTC),
            )
        )
        for booking in bookings:
            self.db.add(
                OutboxJob(
                    operator_id=self.operator_id,
                    booking_order_id=booking.booking_order_id,
                    job_type="ghl_sync_appointment",
                    idempotency_key=f"booking:{booking.id}:ghl_appointment:calendar:{uuid.uuid4().hex}",
                    payload={"booking_id": str(booking.id)},
                    status="pending",
                )
            )
        self.db.commit()
        try:
            OutboxService(self.db, get_settings()).process(limit=100, prefer_newest=True)
        except Exception:
            logger.exception("Inline outbox processing failed after calendar mutation")

    def delete_calendar(self, entity_id: uuid.UUID) -> None:
        entity = self.get_calendar(entity_id)
        if entity.deleted_at is not None:
            raise NotFoundError("Calendar not found")
        calendar_mapping = self.db.scalar(
            select(GHLCalendarMapping).where(
                GHLCalendarMapping.operator_id == self.operator_id,
                GHLCalendarMapping.calendar_id == entity.id,
            )
        )
        booking_rows = self.db.execute(
            select(Booking.id, Booking.booking_order_id).where(Booking.calendar_id == entity.id)
        ).all()
        booking_ids = [booking_id for booking_id, _ in booking_rows]
        booking_order_ids = [order_id for _, order_id in booking_rows]
        signed_waiver = self.db.scalar(
            select(BookingWaiver.booking_id).where(
                BookingWaiver.booking_id.in_(booking_ids), BookingWaiver.status == "signed"
            )
        ) if booking_ids else None
        if signed_waiver is not None:
            raise ConflictError(
                "This calendar has a signed waiver and cannot be physically deleted. "
                "Preserve the booking record or remove the signed waiver under your "
                "legal-retention policy."
            )
        if booking_ids:
            self.db.execute(
                delete(GHLAppointmentMapping).where(
                    GHLAppointmentMapping.booking_id.in_(booking_ids)
                )
            )
            self.db.execute(
                delete(BookingResource).where(BookingResource.booking_id.in_(booking_ids))
            )
            self.db.execute(
                delete(BookingWaiver).where(BookingWaiver.booking_id.in_(booking_ids))
            )
            self.db.execute(
                delete(BookingNote).where(BookingNote.booking_id.in_(booking_ids))
            )
            self.db.execute(
                delete(BookingFinancialAllocation).where(
                    BookingFinancialAllocation.booking_id.in_(booking_ids)
                )
            )
            self.db.execute(delete(Booking).where(Booking.id.in_(booking_ids)))
            if booking_order_ids:
                self.db.execute(
                    delete(OutboxJob).where(
                        OutboxJob.booking_order_id.in_(booking_order_ids),
                        OutboxJob.job_type.in_(
                            ("ghl_sync_appointment", "ghl_cancel_appointment")
                        ),
                    )
                )
        self.db.execute(
            delete(OutboxJob).where(
                OutboxJob.operator_id == self.operator_id,
                OutboxJob.job_type == "ghl_sync_calendar",
                OutboxJob.payload["calendar_id"].astext == str(entity.id),
                OutboxJob.status.in_(("pending", "failed")),
            )
        )
        entity.deleted_at = datetime.now(UTC)
        entity.is_active = False
        entity.public_booking_enabled = False
        self.db.execute(
            delete(StaffAssignment).where(
                StaffAssignment.calendar_id == entity.id,
                StaffAssignment.end_at > datetime.now(UTC),
            )
        )
        if calendar_mapping is not None and calendar_mapping.ghl_calendar_id:
            self.db.add(
                OutboxJob(
                    operator_id=self.operator_id,
                    job_type="ghl_delete_calendar",
                    idempotency_key=f"calendar:{entity.id}:delete",
                    payload={
                        "calendar_id": str(entity.id),
                        "ghl_calendar_id": calendar_mapping.ghl_calendar_id,
                    },
                    status="pending",
                )
            )
        self.db.commit()
        try:
            OutboxService(self.db, get_settings()).process(limit=100, prefer_newest=True)
        except Exception:
            logger.exception("Inline outbox processing failed after calendar deletion")

    def list_hours(self, calendar_id: uuid.UUID) -> list[CalendarHour]:
        self.get_calendar(calendar_id)
        return list(
            self.db.scalars(
                select(CalendarHour)
                .where(CalendarHour.calendar_id == calendar_id)
                .order_by(CalendarHour.day_of_week, CalendarHour.start_time)
            )
        )

    def replace_hours(
        self, calendar_id: uuid.UUID, data: CalendarHoursReplace
    ) -> list[CalendarHour]:
        calendar = self.get_calendar(calendar_id)
        self.db.execute(delete(CalendarHour).where(CalendarHour.calendar_id == calendar_id))
        entities = [
            CalendarHour(calendar_id=calendar_id, **item.model_dump()) for item in data.hours
        ]
        self.db.add_all(entities)
        self.db.commit()
        self._queue_ghl_calendar_sync(calendar)
        return self.list_hours(calendar_id)

    def list_date_hours(self, calendar_id: uuid.UUID) -> list[CalendarDateHour]:
        self.get_calendar(calendar_id)
        return list(
            self.db.scalars(
                select(CalendarDateHour)
                .where(CalendarDateHour.calendar_id == calendar_id)
                .order_by(CalendarDateHour.start_date, CalendarDateHour.start_time)
            )
        )

    def replace_date_hours(
        self, calendar_id: uuid.UUID, data: CalendarDateHoursReplace
    ) -> list[CalendarDateHour]:
        calendar = self.get_calendar(calendar_id)
        self.db.execute(
            delete(CalendarDateHour).where(CalendarDateHour.calendar_id == calendar_id)
        )
        self.db.add_all(
            [CalendarDateHour(calendar_id=calendar_id, **item.model_dump()) for item in data.hours]
        )
        self.db.commit()
        self._queue_ghl_calendar_sync(calendar)
        return self.list_date_hours(calendar_id)

    def list_pushed_slots(self, calendar_id: uuid.UUID) -> list[dict[str, Any]]:
        """Upcoming pushed starts, each with its end derived from the current duration."""
        calendar = self.get_calendar(calendar_id)
        length = timedelta(minutes=calendar.duration_minutes)
        rows = self.db.scalars(
            select(CalendarPushedSlot)
            .where(
                CalendarPushedSlot.calendar_id == calendar_id,
                CalendarPushedSlot.start_at >= datetime.now(UTC),
            )
            .order_by(CalendarPushedSlot.start_at)
        )
        return [{**row.__dict__, "end_at": row.start_at + length} for row in rows]

    def push_slots(self, calendar_id: uuid.UUID, data: PushedSlotsCreate) -> list[dict[str, Any]]:
        """Offer explicit start times. Wall times are interpreted in the operator's zone."""
        calendar = self.get_calendar(calendar_id)
        zone_name = str(self._operator_zone())
        now = datetime.now(UTC)
        starts: set[datetime] = set()
        for item in data.slots:
            start = local_datetime(item.day, item.start_time, zone_name)
            if not wall_time_exists(start):
                raise ConflictError(
                    f"{item.start_time:%H:%M} does not exist on {item.day} (daylight saving change)"
                )
            if start <= now:
                raise ConflictError("Pushed availability must be in the future")
            starts.add(start)
        existing = set(
            self.db.scalars(
                select(CalendarPushedSlot.start_at).where(
                    CalendarPushedSlot.calendar_id == calendar_id,
                    CalendarPushedSlot.start_at.in_(starts),
                )
            )
        )
        if existing:
            raise ConflictError("That start time has already been pushed for this calendar")
        self.db.add_all(
            [CalendarPushedSlot(calendar_id=calendar_id, start_at=start) for start in starts]
        )
        self.db.commit()
        self._queue_ghl_calendar_sync(calendar)
        return self.list_pushed_slots(calendar_id)

    def delete_pushed_slot(self, calendar_id: uuid.UUID, slot_id: uuid.UUID) -> None:
        """Stops offering the time. Bookings already made for it are kept."""
        calendar = self.get_calendar(calendar_id)
        result = self.db.execute(
            delete(CalendarPushedSlot).where(
                CalendarPushedSlot.id == slot_id, CalendarPushedSlot.calendar_id == calendar_id
            )
        )
        if result.rowcount != 1:
            raise NotFoundError()
        self.db.commit()
        self._queue_ghl_calendar_sync(calendar)

    def replace_blocks(
        self, calendar_id: uuid.UUID, data: CalendarBlocksReplace
    ) -> list[dict[str, Any]]:
        """Replace all blocks with whole-day ranges in operator-local time.

        A range is inclusive of end_date, so it ends at midnight of the following
        day. Conversion uses the operator's IANA zone so DST is handled correctly.
        """
        self.get_calendar(calendar_id)
        zone = self.db.scalar(select(Operator.time_zone).where(Operator.id == self.operator_id))
        self.db.execute(delete(CalendarBlock).where(CalendarBlock.calendar_id == calendar_id))
        self.db.add_all(
            [
                CalendarBlock(
                    calendar_id=calendar_id,
                    start_at=local_datetime(item.start_date, time(0, 0), zone or "UTC"),
                    end_at=local_datetime(
                        item.end_date + timedelta(days=1), time(0, 0), zone or "UTC"
                    ),
                    reason=item.reason,
                )
                for item in data.blocks
            ]
        )
        self.db.commit()
        self._queue_ghl_calendar_sync(self.get_calendar(calendar_id))
        return self.list_blocks(calendar_id)

    def _operator_zone(self):
        return require_timezone(
            self.db.scalar(select(Operator.time_zone).where(Operator.id == self.operator_id))
            or "UTC"
        )

    @staticmethod
    def _block_payload(row: CalendarBlock, zone) -> dict[str, Any]:
        return {
            **row.__dict__,
            "start_date": row.start_at.astimezone(zone).date(),
            "end_date": (row.end_at.astimezone(zone) - timedelta(seconds=1)).date(),
        }

    def list_blocks(self, calendar_id: uuid.UUID) -> list[dict[str, Any]]:
        """Blocks with their operator-local date span derived server-side.

        end_at is exclusive (midnight after the last blocked day), so the final
        blocked date is taken from an instant just before it.
        """
        self.get_calendar(calendar_id)
        zone = self._operator_zone()
        rows = self.db.scalars(
            select(CalendarBlock)
            .where(CalendarBlock.calendar_id == calendar_id)
            .order_by(CalendarBlock.start_at)
        )
        return [self._block_payload(row, zone) for row in rows]

    def create_block(self, calendar_id: uuid.UUID, data: CalendarBlockWrite) -> dict[str, Any]:
        self.get_calendar(calendar_id)
        entity = CalendarBlock(calendar_id=calendar_id, **data.model_dump())
        self.db.add(entity)
        self.db.commit()
        self.db.refresh(entity)
        return self._block_payload(entity, self._operator_zone())

    def update_block(
        self, calendar_id: uuid.UUID, block_id: uuid.UUID, data: CalendarBlockWrite
    ) -> dict[str, Any]:
        self.get_calendar(calendar_id)
        entity = self.db.scalar(
            select(CalendarBlock).where(
                CalendarBlock.id == block_id, CalendarBlock.calendar_id == calendar_id
            )
        )
        if entity is None:
            raise NotFoundError()
        _apply(entity, data.model_dump())
        self.db.commit()
        self.db.refresh(entity)
        self._queue_ghl_calendar_sync(self.get_calendar(calendar_id))
        return self._block_payload(entity, self._operator_zone())

    def delete_block(self, calendar_id: uuid.UUID, block_id: uuid.UUID) -> None:
        self.get_calendar(calendar_id)
        result = self.db.execute(
            delete(CalendarBlock).where(
                CalendarBlock.id == block_id, CalendarBlock.calendar_id == calendar_id
            )
        )
        if result.rowcount != 1:
            raise NotFoundError()
        self.db.commit()
        self._queue_ghl_calendar_sync(self.get_calendar(calendar_id))

    def list_calendar_resources(self, calendar_id: uuid.UUID) -> list[dict[str, Any]]:
        self.get_calendar(calendar_id)
        rows = self.db.execute(
            select(
                CalendarResource.resource_id,
                Resource.name,
                Resource.quantity,
                CalendarResource.default_quantity_per_unit,
            )
            .join(Resource, Resource.id == CalendarResource.resource_id)
            .where(
                CalendarResource.calendar_id == calendar_id,
                Resource.operator_id == self.operator_id,
                Resource.deleted_at.is_(None),
                Resource.is_active.is_(True),
            )
            .order_by(Resource.name)
        )
        return [
            {
                "resource_id": resource_id,
                "name": name,
                "total_quantity": quantity,
                "default_quantity_per_unit": per_unit,
            }
            for resource_id, name, quantity, per_unit in rows
        ]

    def replace_calendar_resources(
        self, calendar_id: uuid.UUID, data: CalendarResourcesReplace
    ) -> list[dict[str, Any]]:
        self.get_calendar(calendar_id)
        for mapping in data.resources:
            self._owned(Resource, mapping.resource_id, active=True)
        self.db.execute(delete(CalendarResource).where(CalendarResource.calendar_id == calendar_id))
        self.db.add_all(
            [
                CalendarResource(calendar_id=calendar_id, **item.model_dump())
                for item in data.resources
            ]
        )
        self.db.commit()
        self._queue_ghl_appointment_sync(calendar_id)
        return self.list_calendar_resources(calendar_id)
