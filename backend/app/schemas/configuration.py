import uuid
from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import EntityModel
from app.utils.timezone import require_timezone


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    address: str = Field(min_length=1, max_length=1000)
    is_active: bool = True


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    address: str | None = Field(default=None, min_length=1, max_length=1000)
    is_active: bool | None = None


class LocationRead(EntityModel):
    name: str
    address: str
    is_active: bool
    calendars_count: int = 0


class ResourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    resource_type: str = Field(default="equipment", min_length=1, max_length=80)
    quantity: int = Field(ge=0, le=1_000_000)
    capacity_limit: int | None = Field(default=None, ge=0, le=1_000_000)
    notes: str | None = Field(default=None, max_length=2_000)
    is_active: bool = True


class ResourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    resource_type: str | None = Field(default=None, min_length=1, max_length=80)
    quantity: int | None = Field(default=None, ge=0, le=1_000_000)
    capacity_limit: int | None = Field(default=None, ge=0, le=1_000_000)
    notes: str | None = Field(default=None, max_length=2_000)
    is_active: bool | None = None


class ResourceRead(EntityModel):
    name: str
    resource_type: str
    quantity: int
    capacity_limit: int | None
    notes: str | None
    is_active: bool
    calendars_count: int = 0


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=160)
    display_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    sort_order: int = Field(default=0, ge=-100_000, le=100_000)
    is_active: bool = True


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=160)
    display_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    sort_order: int | None = Field(default=None, ge=-100_000, le=100_000)
    is_active: bool | None = None


class CategoryRead(EntityModel):
    name: str
    slug: str
    display_color: str | None
    sort_order: int
    is_active: bool
    calendars_count: int = 0


AvailabilityMode = Literal["day_wise", "date_wise", "pushed"]
PublicBookingMode = Literal["online", "call_to_book", "closed"]
StaffPoolRole = Literal["Captain", "First Mate", "Guide", "Deckhand", "Instructor"]


def _normalize_staff_roles(value: list[StaffPoolRole]) -> list[StaffPoolRole]:
    return list(dict.fromkeys(value))


class CalendarCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=160)
    headline: str | None = Field(default=None, max_length=240)
    description: str | None = Field(default=None, max_length=10_000)
    booking_instructions: str | None = Field(default=None, max_length=10_000)
    hero_image_url: str | None = Field(default=None, max_length=2_000)
    gallery_image_urls: list[str] = Field(default_factory=list, max_length=12)
    calendar_category_id: uuid.UUID | None = None
    departure_location_id: uuid.UUID | None = None
    is_active: bool = True
    public_booking_enabled: bool = True
    duration_minutes: int = Field(gt=0, le=10_080)
    slot_interval_minutes: int = Field(default=30, gt=0, le=1440)
    max_units_per_booking: int | None = Field(default=None, gt=0, le=100_000)
    base_price_minor: int = Field(default=0, ge=0)
    currency: str = Field(default="usd", pattern=r"^[a-zA-Z]{3}$")
    availability_mode: AvailabilityMode = "day_wise"
    required_staff_roles: list[StaffPoolRole] = Field(default_factory=list, max_length=5)
    minimum_party_size: int | None = Field(default=None, gt=0, le=100_000)
    maximum_party_size: int | None = Field(default=None, gt=0, le=100_000)
    booking_fee_bps: int = Field(default=0, ge=0, le=10_000)
    tax_bps: int = Field(default=0, ge=0, le=10_000)
    public_booking_mode: PublicBookingMode = "online"
    booking_cutoff_minutes: int | None = Field(default=None, ge=0, le=100_000)
    call_to_book_phone: str | None = Field(default=None, max_length=40)

    @field_validator("required_staff_roles")
    @classmethod
    def normalize_staff_roles(cls, value: list[StaffPoolRole]) -> list[StaffPoolRole]:
        return _normalize_staff_roles(value)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def validate_party_size(self) -> "CalendarCreate":
        if self.minimum_party_size is not None and self.maximum_party_size is not None:
            if self.minimum_party_size > self.maximum_party_size:
                raise ValueError("minimum_party_size cannot exceed maximum_party_size")
        return self


class CalendarUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=160)
    headline: str | None = Field(default=None, max_length=240)
    description: str | None = Field(default=None, max_length=10_000)
    booking_instructions: str | None = Field(default=None, max_length=10_000)
    hero_image_url: str | None = Field(default=None, max_length=2_000)
    gallery_image_urls: list[str] | None = Field(default=None, max_length=12)
    calendar_category_id: uuid.UUID | None = None
    departure_location_id: uuid.UUID | None = None
    is_active: bool | None = None
    public_booking_enabled: bool | None = None
    duration_minutes: int | None = Field(default=None, gt=0, le=10_080)
    slot_interval_minutes: int | None = Field(default=None, gt=0, le=1440)
    max_units_per_booking: int | None = Field(default=None, gt=0, le=100_000)
    base_price_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[a-zA-Z]{3}$")
    availability_mode: AvailabilityMode | None = None
    required_staff_roles: list[StaffPoolRole] | None = Field(default=None, max_length=5)
    minimum_party_size: int | None = Field(default=None, gt=0, le=100_000)
    maximum_party_size: int | None = Field(default=None, gt=0, le=100_000)
    booking_fee_bps: int | None = Field(default=None, ge=0, le=10_000)
    tax_bps: int | None = Field(default=None, ge=0, le=10_000)
    public_booking_mode: PublicBookingMode | None = None
    booking_cutoff_minutes: int | None = Field(default=None, ge=0, le=100_000)
    call_to_book_phone: str | None = Field(default=None, max_length=40)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.lower() if value else value

    @field_validator("required_staff_roles")
    @classmethod
    def normalize_staff_roles(cls, value: list[StaffPoolRole] | None) -> list[StaffPoolRole] | None:
        return _normalize_staff_roles(value) if value is not None else None


class CalendarRead(EntityModel):
    calendar_category_id: uuid.UUID | None
    departure_location_id: uuid.UUID | None
    name: str
    slug: str
    headline: str | None
    description: str | None
    booking_instructions: str | None
    hero_image_url: str | None
    gallery_image_urls: list[str]
    is_active: bool
    public_booking_enabled: bool
    duration_minutes: int
    slot_interval_minutes: int
    max_units_per_booking: int | None
    base_price_minor: int
    currency: str
    availability_mode: str
    required_staff_roles: list[str]
    minimum_party_size: int | None
    maximum_party_size: int | None
    booking_fee_bps: int
    tax_bps: int
    public_booking_mode: str
    booking_cutoff_minutes: int | None
    call_to_book_phone: str | None


class CalendarHourWrite(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def validate_order(self) -> "CalendarHourWrite":
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        return self


class CalendarHoursReplace(BaseModel):
    hours: list[CalendarHourWrite] = Field(max_length=100)


class CalendarHourRead(EntityModel):
    calendar_id: uuid.UUID
    day_of_week: int
    start_time: time
    end_time: time


class CalendarDateHourWrite(BaseModel):
    """One opening interval within an explicit date range."""

    start_date: date
    end_date: date
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def validate_order(self) -> "CalendarDateHourWrite":
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        return self


class CalendarDateHoursReplace(BaseModel):
    hours: list[CalendarDateHourWrite] = Field(max_length=365)


class CalendarDateHourRead(EntityModel):
    calendar_id: uuid.UUID
    start_date: date
    end_date: date
    start_time: time
    end_time: time


class PushedSlotWrite(BaseModel):
    """A pushed start as operator-local wall time; the server converts it."""

    day: date
    start_time: time


class PushedSlotsCreate(BaseModel):
    slots: list[PushedSlotWrite] = Field(min_length=1, max_length=100)


class PushedSlotRead(EntityModel):
    calendar_id: uuid.UUID
    start_at: datetime
    end_at: datetime


class CalendarBlockDateRange(BaseModel):
    """A blocked interval expressed as whole dates in operator-local time."""

    start_date: date
    end_date: date
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_order(self) -> "CalendarBlockDateRange":
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class CalendarBlocksReplace(BaseModel):
    blocks: list[CalendarBlockDateRange] = Field(max_length=365)


class CalendarBlockWrite(BaseModel):
    start_at: datetime
    end_at: datetime
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_interval(self) -> "CalendarBlockWrite":
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("Block timestamps must include an offset")
        if self.start_at >= self.end_at:
            raise ValueError("start_at must be before end_at")
        return self


class CalendarBlockRead(EntityModel):
    calendar_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    start_date: date
    end_date: date
    reason: str | None


class CalendarResourceWrite(BaseModel):
    resource_id: uuid.UUID
    default_quantity_per_unit: int = Field(gt=0, le=1_000_000)


class CalendarResourcesReplace(BaseModel):
    resources: list[CalendarResourceWrite] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_resources(self) -> "CalendarResourcesReplace":
        ids = [item.resource_id for item in self.resources]
        if len(ids) != len(set(ids)):
            raise ValueError("A resource can only be mapped once")
        return self


class CalendarResourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resource_id: uuid.UUID
    name: str
    total_quantity: int
    default_quantity_per_unit: int


class CustomerTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    plural_name: str = Field(min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=1000)
    seat_count: int = Field(default=1, gt=0, le=1000)
    external_provider: str | None = Field(default=None, max_length=80)
    external_id: str | None = Field(default=None, max_length=160)
    is_active: bool = True


class CustomerTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    plural_name: str | None = Field(default=None, min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=1000)
    seat_count: int | None = Field(default=None, gt=0, le=1000)
    is_active: bool | None = None


class CustomerTypeRead(EntityModel):
    name: str
    plural_name: str
    note: str | None
    seat_count: int
    external_provider: str | None
    external_id: str | None
    is_active: bool


class RateResourceWrite(BaseModel):
    resource_id: uuid.UUID
    quantity_per_unit: int = Field(gt=0, le=1_000_000)


class CalendarRateWrite(BaseModel):
    customer_type_id: uuid.UUID
    price_minor: int = Field(ge=0)
    note: str | None = Field(default=None, max_length=1000)
    booking_fee_bps: int = Field(default=0, ge=0, le=10_000)
    tax_bps: int = Field(default=0, ge=0, le=10_000)
    is_tax_inclusive: bool = False
    is_fee_inclusive: bool = False
    external_provider: str | None = Field(default=None, max_length=80)
    external_id: str | None = Field(default=None, max_length=160)
    is_active: bool = True
    resources: list[RateResourceWrite] = Field(default_factory=list, max_length=100)


class CalendarRatesReplace(BaseModel):
    rates: list[CalendarRateWrite] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_types(self) -> "CalendarRatesReplace":
        ids = [item.customer_type_id for item in self.rates]
        if len(ids) != len(set(ids)):
            raise ValueError("A calendar can only have one active rate per customer type")
        return self


class RateResourceRead(BaseModel):
    resource_id: uuid.UUID
    name: str
    quantity_per_unit: int
    total_quantity: int


class CalendarRateRead(EntityModel):
    calendar_id: uuid.UUID
    customer_type_id: uuid.UUID
    customer_type_name: str
    customer_type_plural_name: str
    customer_type_note: str | None
    seat_count: int
    price_minor: int
    booking_fee_bps: int
    tax_bps: int
    is_tax_inclusive: bool
    is_fee_inclusive: bool
    external_provider: str | None
    external_id: str | None
    is_active: bool
    resources: list[RateResourceRead] = Field(default_factory=list)


class OperatorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    time_zone: str | None = None
    public_booking_enabled: bool | None = None

    @field_validator("time_zone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("time_zone cannot be blank")
        require_timezone(normalized)
        return normalized
