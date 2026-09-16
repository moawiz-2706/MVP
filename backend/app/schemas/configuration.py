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
    quantity: int = Field(ge=0, le=1_000_000)
    is_active: bool = True


class ResourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    quantity: int | None = Field(default=None, ge=0, le=1_000_000)
    is_active: bool | None = None


class ResourceRead(EntityModel):
    name: str
    quantity: int
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


class CalendarCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=160)
    description: str | None = Field(default=None, max_length=10_000)
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

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.lower()


class CalendarUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=160)
    description: str | None = Field(default=None, max_length=10_000)
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

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.lower() if value else value


class CalendarRead(EntityModel):
    calendar_category_id: uuid.UUID | None
    departure_location_id: uuid.UUID | None
    name: str
    slug: str
    description: str | None
    is_active: bool
    public_booking_enabled: bool
    duration_minutes: int
    slot_interval_minutes: int
    max_units_per_booking: int | None
    base_price_minor: int
    currency: str
    availability_mode: str


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


class OperatorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    time_zone: str | None = None
    public_booking_enabled: bool | None = None

    @field_validator("time_zone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value:
            require_timezone(value)
        return value
