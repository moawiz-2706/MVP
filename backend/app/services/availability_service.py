import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from math import floor

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.entities import (
    Booking,
    BookingResource,
    Calendar,
    CalendarBlock,
    CalendarDateHour,
    CalendarHour,
    CalendarRate,
    CalendarRateResource,
    CalendarPushedSlot,
    CalendarResource,
    CustomerType,
    DepartureLocation,
    Operator,
    Resource,
)
from app.schemas.availability import (
    AvailabilityCheckResponse,
    AvailabilityRate,
    AvailabilitySlot,
    PublicAvailabilityResponse,
    PublicCalendarSummary,
    ResourceAvailability,
)
from app.services.capacity import CapacityInterval, reserved_for_interval
from app.services.staffing_service import pool_readiness_for_interval
from app.utils.timezone import local_datetime, require_timezone


class AvailabilityService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _operator_timezone(operator: Operator) -> str:
        return (operator.time_zone or "UTC").strip() or "UTC"

    def _calendar(
        self,
        calendar_id: uuid.UUID,
        *,
        operator_id: uuid.UUID | None = None,
        public: bool = False,
    ) -> tuple[Calendar, Operator]:
        conditions = [Calendar.id == calendar_id, Calendar.deleted_at.is_(None)]
        if operator_id:
            conditions.append(Calendar.operator_id == operator_id)
        if public:
            conditions.extend(
                [
                    Calendar.is_active.is_(True),
                    Calendar.public_booking_enabled.is_(True),
                    Operator.is_active.is_(True),
                    Operator.public_booking_enabled.is_(True),
                ]
            )
        row = self.db.execute(
            select(Calendar, Operator)
            .join(Operator, Operator.id == Calendar.operator_id)
            .where(*conditions)
        ).one_or_none()
        if row is None:
            raise NotFoundError("Calendar not found")
        return row

    def _mappings(self, calendar_id: uuid.UUID) -> list[tuple[Resource, int]]:
        return list(
            self.db.execute(
                select(Resource, CalendarResource.default_quantity_per_unit)
                .join(CalendarResource, CalendarResource.resource_id == Resource.id)
                .where(CalendarResource.calendar_id == calendar_id)
                .order_by(Resource.id)
            ).all()
        )

    def _rate_mappings(
        self, calendar_id: uuid.UUID
    ) -> list[tuple[CalendarRate, CustomerType, list[tuple[Resource, int]]]]:
        rows = self.db.execute(
            select(CalendarRate, CustomerType)
            .join(CustomerType, CustomerType.id == CalendarRate.customer_type_id)
            .where(
                CalendarRate.calendar_id == calendar_id,
                CalendarRate.deleted_at.is_(None),
                CalendarRate.is_active.is_(True),
                CustomerType.deleted_at.is_(None),
                CustomerType.is_active.is_(True),
            )
            .order_by(CalendarRate.name_snapshot)
        ).all()
        result = []
        for rate, customer_type in rows:
            mappings = list(
                self.db.execute(
                    select(Resource, CalendarRateResource.quantity_per_unit)
                    .join(CalendarRateResource, CalendarRateResource.resource_id == Resource.id)
                    .where(CalendarRateResource.rate_id == rate.id)
                    .order_by(Resource.id)
                ).all()
            )
            result.append((rate, customer_type, mappings))
        return result

    def _openings_for_date(self, calendar: Calendar, local_date: date) -> list[tuple[time, time]]:
        """Opening intervals that apply on a given operator-local date.

        Exactly one mode governs a calendar. In date_wise mode only explicit date
        ranges covering this date apply; the recurring weekly rows are ignored
        entirely (and vice versa), so the two can never silently combine.
        """
        if calendar.availability_mode == "date_wise":
            rows = self.db.scalars(
                select(CalendarDateHour)
                .where(
                    CalendarDateHour.calendar_id == calendar.id,
                    CalendarDateHour.start_date <= local_date,
                    CalendarDateHour.end_date >= local_date,
                )
                .order_by(CalendarDateHour.start_time)
            )
        else:
            rows = self.db.scalars(
                select(CalendarHour)
                .where(
                    CalendarHour.calendar_id == calendar.id,
                    CalendarHour.day_of_week == local_date.weekday(),
                )
                .order_by(CalendarHour.start_time)
            )
        return [(row.start_time, row.end_time) for row in rows]

    def _pushed_starts(
        self, calendar_id: uuid.UUID, range_start: datetime, range_end: datetime
    ) -> list[datetime]:
        return list(
            self.db.scalars(
                select(CalendarPushedSlot.start_at)
                .where(
                    CalendarPushedSlot.calendar_id == calendar_id,
                    CalendarPushedSlot.start_at >= range_start,
                    CalendarPushedSlot.start_at < range_end,
                )
                .order_by(CalendarPushedSlot.start_at)
            )
        )

    def _within_hours(
        self, calendar: Calendar, operator: Operator, start_at: datetime, end_at: datetime
    ) -> bool:
        if calendar.availability_mode == "pushed":
            # Only the exact pushed instant is offered; slot intervals and
            # opening windows do not apply, and the end is start + duration.
            return bool(
                self._pushed_starts(calendar.id, start_at, start_at + timedelta(microseconds=1))
            )
        zone = require_timezone(self._operator_timezone(operator))
        local_start, local_end = start_at.astimezone(zone), end_at.astimezone(zone)
        if local_start.date() != local_end.date():
            return False
        return any(
            local_start.time().replace(tzinfo=None) >= opening_start
            and local_end.time().replace(tzinfo=None) <= opening_end
            for opening_start, opening_end in self._openings_for_date(calendar, local_start.date())
        )

    def _is_blocked(self, calendar_id: uuid.UUID, start_at: datetime, end_at: datetime) -> bool:
        return (
            self.db.scalar(
                select(CalendarBlock.id).where(
                    CalendarBlock.calendar_id == calendar_id,
                    CalendarBlock.start_at < end_at,
                    CalendarBlock.end_at > start_at,
                )
            )
            is not None
        )

    def _reservations(
        self,
        resource_ids: list[uuid.UUID],
        start_at: datetime,
        end_at: datetime,
        *,
        exclude_booking_ids: set[uuid.UUID] | None = None,
    ) -> dict[uuid.UUID, list[CapacityInterval]]:
        if not resource_ids:
            return {}
        now = datetime.now(UTC)
        statement = (
            select(
                BookingResource.resource_id,
                Booking.start_at,
                Booking.end_at,
                BookingResource.quantity,
            )
            .join(Booking, Booking.id == BookingResource.booking_id)
            .where(
                BookingResource.resource_id.in_(resource_ids),
                Booking.start_at < end_at,
                Booking.end_at > start_at,
                or_(
                    Booking.status == "confirmed",
                    (Booking.status == "pending_payment") & (Booking.hold_expires_at > now),
                ),
            )
        )
        if exclude_booking_ids:
            statement = statement.where(Booking.id.not_in(exclude_booking_ids))
        rows = self.db.execute(statement)
        grouped: dict[uuid.UUID, list[CapacityInterval]] = defaultdict(list)
        for resource_id, reserved_start, reserved_end, quantity in rows:
            grouped[resource_id].append(
                CapacityInterval(reserved_start, reserved_end, quantity)
            )
        return grouped

    def check(
        self,
        calendar_id: uuid.UUID,
        start_at: datetime,
        units: int,
        *,
        operator_id: uuid.UUID | None = None,
        public: bool = False,
        exclude_booking_ids: set[uuid.UUID] | None = None,
        resource_mappings: list[tuple[Resource, int]] | None = None,
    ) -> AvailabilityCheckResponse:
        if start_at.tzinfo is None:
            raise ValueError("start_at must include an offset")
        calendar, operator = self._calendar(
            calendar_id, operator_id=operator_id, public=public
        )
        end_at = start_at + timedelta(minutes=calendar.duration_minutes)
        within_hours = self._within_hours(calendar, operator, start_at, end_at)
        blocked = self._is_blocked(calendar.id, start_at, end_at)
        policy_reason = None
        if public and calendar.public_booking_mode == "closed":
            policy_reason = "Online booking is closed for this calendar"
        elif public and calendar.public_booking_mode == "call_to_book":
            policy_reason = "This experience requires a call to book"
        elif (
            public
            and calendar.booking_cutoff_minutes is not None
            and datetime.now(UTC)
            >= start_at.astimezone(UTC) - timedelta(minutes=calendar.booking_cutoff_minutes)
        ):
            policy_reason = "Online booking has passed the cutoff time"
        mappings = self._mappings(calendar.id) if resource_mappings is None else resource_mappings
        reservations = self._reservations(
            [resource.id for resource, _ in mappings],
            start_at,
            end_at,
            exclude_booking_ids=exclude_booking_ids,
        )

        details: list[ResourceAvailability] = []
        inventory_max: int | None = None
        for resource, per_unit in mappings:
            reserved = reserved_for_interval(
                reservations.get(resource.id, []), start_at, end_at
            )
            available = (
                max(0, resource.quantity - reserved)
                if resource.is_active and not resource.deleted_at
                else 0
            )
            resource_max = floor(available / per_unit)
            inventory_max = (
                resource_max if inventory_max is None else min(inventory_max, resource_max)
            )
            requested = units * per_unit
            details.append(
                ResourceAvailability(
                    resource_id=resource.id,
                    name=resource.name,
                    total=resource.quantity,
                    reserved=reserved,
                    available=available,
                    required_per_unit=per_unit,
                    requested=requested,
                    sufficient=resource.is_active
                    and resource.deleted_at is None
                    and requested <= available,
                )
            )

        if inventory_max is None:
            inventory_max = calendar.max_units_per_booking or 1
        elif calendar.max_units_per_booking is not None:
            inventory_max = min(inventory_max, calendar.max_units_per_booking)
        resource_sufficient = all(detail.sufficient for detail in details)
        staffing = (
            pool_readiness_for_interval(self.db, operator_id, calendar.id, start_at, end_at)
            if operator_id and calendar.required_staff_roles
            else None
        )
        reason = None
        if not calendar.is_active:
            reason = "Calendar is inactive"
        elif policy_reason:
            reason = policy_reason
        elif not within_hours:
            reason = "Requested time is outside calendar hours"
        elif blocked:
            reason = "Requested time is blocked"
        elif not resource_sufficient or units > inventory_max:
            reason = "Insufficient resource inventory"
        elif staffing is not None and not staffing.ready:
            reason = staffing.reason or "Required staff are unavailable for this time"
        return AvailabilityCheckResponse(
            available=reason is None,
            start_at=start_at,
            end_at=end_at,
            requested_units=units,
            max_bookable_units=max(0, inventory_max) if within_hours and not blocked else 0,
            resources=details,
            reason=reason,
        )

    @staticmethod
    def _valid_local(value: datetime, timezone_name: str) -> bool:
        zone = require_timezone(timezone_name)
        return value.astimezone(UTC).astimezone(zone).replace(fold=value.fold) == value

    def _candidate_starts(
        self, calendar: Calendar, operator: Operator, day: date
    ) -> list[datetime]:
        """Start instants to offer on an operator-local date, before capacity checks."""
        if calendar.availability_mode == "pushed":
            return self._pushed_starts(
                calendar.id,
                local_datetime(day, time(0), self._operator_timezone(operator)),
                local_datetime(day + timedelta(days=1), time(0), self._operator_timezone(operator)),
            )
        starts: list[datetime] = []
        for opening_start, opening_end in self._openings_for_date(calendar, day):
            candidate = local_datetime(day, opening_start, self._operator_timezone(operator))
            closing = local_datetime(day, opening_end, self._operator_timezone(operator))
            while candidate + timedelta(minutes=calendar.duration_minutes) <= closing:
                if self._valid_local(candidate, self._operator_timezone(operator)):
                    starts.append(candidate)
                candidate += timedelta(minutes=calendar.slot_interval_minutes)
        return starts

    def public_day(
        self,
        operator_slug: str,
        calendar_slug: str,
        day: date,
        display_timezone: str | None = None,
    ) -> PublicAvailabilityResponse:
        row = self.db.execute(
            select(Calendar, Operator, DepartureLocation)
            .join(Operator, Operator.id == Calendar.operator_id)
            .outerjoin(DepartureLocation, DepartureLocation.id == Calendar.departure_location_id)
            .where(
                Operator.slug == operator_slug,
                Operator.is_active.is_(True),
                Operator.public_booking_enabled.is_(True),
                Calendar.slug == calendar_slug,
                Calendar.is_active.is_(True),
                Calendar.public_booking_enabled.is_(True),
                Calendar.deleted_at.is_(None),
            )
        ).one_or_none()
        if row is None:
            raise NotFoundError("Public calendar not found")
        calendar, operator, location = row
        operator_timezone = self._operator_timezone(operator)
        operator_zone = require_timezone(operator_timezone)
        display_zone = require_timezone((display_timezone or operator_timezone).strip() or "UTC")
        if display_timezone:
            display_start = local_datetime(day, time(0), display_timezone)
            display_end = local_datetime(day + timedelta(days=1), time(0), display_timezone)
            first_operator_day = display_start.astimezone(operator_zone).date() - timedelta(days=1)
            last_operator_day = display_end.astimezone(operator_zone).date() + timedelta(days=1)
            source_days = [
                first_operator_day + timedelta(days=offset)
                for offset in range((last_operator_day - first_operator_day).days + 1)
            ]
        else:
            source_days = [day]
        now = datetime.now(UTC)
        slots: list[AvailabilitySlot] = []
        candidates = [
            candidate
            for source_day in source_days
            for candidate in self._candidate_starts(calendar, operator, source_day)
            if candidate.astimezone(UTC) > now
            and candidate.astimezone(display_zone).date() == day
        ]
        if candidates:
            range_start = min(candidates)
            range_end = max(candidates) + timedelta(minutes=calendar.duration_minutes)
            mappings = self._mappings(calendar.id)
            rate_mappings = self._rate_mappings(calendar.id)
            reservations = self._reservations(
                [resource.id for resource, _ in mappings], range_start, range_end
            )
            blocks = list(
                self.db.execute(
                    select(CalendarBlock.start_at, CalendarBlock.end_at).where(
                        CalendarBlock.calendar_id == calendar.id,
                        CalendarBlock.start_at < range_end,
                        CalendarBlock.end_at > range_start,
                    )
                )
            )
            for candidate in candidates:
                end_at = candidate + timedelta(minutes=calendar.duration_minutes)
                blocked = any(
                    block_start < end_at and block_end > candidate
                    for block_start, block_end in blocks
                )
                inventory_max: int | None = None
                for resource, per_unit in mappings:
                    reserved = reserved_for_interval(
                        reservations.get(resource.id, []), candidate, end_at
                    )
                    available = (
                        max(0, resource.quantity - reserved)
                        if resource.is_active and resource.deleted_at is None
                        else 0
                    )
                    resource_max = floor(available / per_unit)
                    inventory_max = (
                        resource_max
                        if inventory_max is None
                        else min(inventory_max, resource_max)
                    )
                if inventory_max is None:
                    rate_inventory_maxes: list[int] = []
                    for _rate, _customer_type, rate_resources in rate_mappings:
                        rate_max: int | None = None
                        for resource, per_unit in rate_resources:
                            reserved = reserved_for_interval(
                                reservations.get(resource.id, []), candidate, end_at
                            )
                            resource_available = (
                                max(0, resource.quantity - reserved)
                                if resource.is_active and resource.deleted_at is None
                                else 0
                            )
                            resource_max = floor(resource_available / per_unit)
                            rate_max = resource_max if rate_max is None else min(rate_max, resource_max)
                        if rate_max is not None:
                            rate_inventory_maxes.append(rate_max)
                    inventory_max = max(rate_inventory_maxes, default=calendar.max_units_per_booking or 1)
                elif calendar.max_units_per_booking is not None:
                    inventory_max = min(inventory_max, calendar.max_units_per_booking)
                # Staff assignment is an operational concern, not a booking
                # capacity rule. A slot remains bookable when no staff member
                # or required role is currently available. Calendar hours,
                # blocks, and resource inventory remain authoritative here.
                inventory_available = not blocked and inventory_max > 0
                cutoff_passed = (
                    calendar.booking_cutoff_minutes is not None
                    and now >= candidate.astimezone(UTC)
                    - timedelta(minutes=calendar.booking_cutoff_minutes)
                )
                staffing = (
                    pool_readiness_for_interval(
                        self.db, calendar.operator_id, calendar.id, candidate, end_at
                    )
                    if calendar.required_staff_roles
                    else None
                )
                if blocked:
                    slot_status = "blocked"
                elif calendar.public_booking_mode == "closed":
                    slot_status = "closed"
                elif calendar.public_booking_mode == "call_to_book":
                    slot_status = "call_to_book"
                elif cutoff_passed:
                    slot_status = "past_cutoff"
                elif staffing is not None and not staffing.ready:
                    slot_status = "staff_unavailable"
                elif inventory_available:
                    slot_status = "bookable_online"
                else:
                    slot_status = "sold_out"
                available = slot_status == "bookable_online"
                rate_details: list[AvailabilityRate] = []
                for rate, customer_type, rate_resources in rate_mappings:
                    rate_max: int | None = None
                    for resource, per_unit in rate_resources:
                        reserved = reserved_for_interval(
                            reservations.get(resource.id, []), candidate, end_at
                        )
                        resource_available = (
                            max(0, resource.quantity - reserved)
                            if resource.is_active and resource.deleted_at is None
                            else 0
                        )
                        resource_max = floor(resource_available / per_unit)
                        rate_max = resource_max if rate_max is None else min(rate_max, resource_max)
                    if rate_max is None:
                        rate_max = calendar.max_units_per_booking or 1
                    if calendar.max_units_per_booking is not None:
                        rate_max = min(rate_max, calendar.max_units_per_booking)
                    rate_details.append(
                        AvailabilityRate(
                            rate_id=rate.id,
                            customer_type_name=customer_type.name,
                            seat_count=customer_type.seat_count,
                            available_quantity=max(0, rate_max) if not blocked else 0,
                            available_seats=max(0, rate_max * customer_type.seat_count)
                            if not blocked
                            else 0,
                        )
                    )
                slots.append(
                    AvailabilitySlot(
                        start_at=candidate,
                        end_at=end_at,
                        max_bookable_units=inventory_max if available else 0,
                        available=available,
                        status=slot_status,
                        rates=rate_details,
                    )
                )
        slots.sort(key=lambda item: item.start_at)
        return PublicAvailabilityResponse(
            date=day,
            time_zone=(display_timezone or operator_timezone).strip() or "UTC",
            calendar=PublicCalendarSummary(
                id=calendar.id,
                operator_name=operator.name,
                operator_slug=operator.slug,
                calendar_name=calendar.name,
                calendar_slug=calendar.slug,
                description=calendar.description,
                duration_minutes=calendar.duration_minutes,
                base_price_minor=calendar.base_price_minor,
                currency=calendar.currency,
                departure_location_name=location.name if location else None,
                departure_location_address=location.address if location else None,
            ),
            slots=slots,
        )

    def calendar_day(
        self, calendar_id: uuid.UUID, operator_id: uuid.UUID, day: date
    ) -> PublicAvailabilityResponse:
        """Return live slots for an authenticated calendar page.

        This deliberately uses the same candidate generation and ``check`` calls
        as the public booking link. The calendar page may view a calendar that is
        not publicly exposed, but it must never implement a second availability
        algorithm.
        """
        calendar, operator = self._calendar(calendar_id, operator_id=operator_id)
        location = self.db.scalar(
            select(DepartureLocation).where(
                DepartureLocation.id == calendar.departure_location_id,
                DepartureLocation.operator_id == operator_id,
            )
        )
        now = datetime.now(UTC)
        slots: list[AvailabilitySlot] = []
        for candidate in self._candidate_starts(calendar, operator, day):
            if candidate.astimezone(UTC) <= now:
                continue
            result = self.check(
                calendar.id,
                candidate,
                1,
                operator_id=operator_id,
            )
            slots.append(
                AvailabilitySlot(
                    start_at=result.start_at,
                    end_at=result.end_at,
                    max_bookable_units=result.max_bookable_units,
                    available=result.available and result.max_bookable_units > 0,
                )
            )
        return PublicAvailabilityResponse(
            date=day,
            time_zone=self._operator_timezone(operator),
            calendar=PublicCalendarSummary(
                id=calendar.id,
                operator_name=operator.name,
                operator_slug=operator.slug,
                calendar_name=calendar.name,
                calendar_slug=calendar.slug,
                description=calendar.description,
                duration_minutes=calendar.duration_minutes,
                base_price_minor=calendar.base_price_minor,
                currency=calendar.currency,
                departure_location_name=location.name if location else None,
                departure_location_address=location.address if location else None,
            ),
            slots=slots,
        )
