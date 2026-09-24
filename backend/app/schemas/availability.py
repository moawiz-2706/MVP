import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator


class AvailabilityCheckRequest(BaseModel):
    calendar_id: uuid.UUID
    start_at: datetime
    units: int = Field(gt=0, le=100_000)

    @model_validator(mode="after")
    def aware_time(self) -> "AvailabilityCheckRequest":
        if self.start_at.tzinfo is None:
            raise ValueError("start_at must include an offset")
        return self


class ResourceAvailability(BaseModel):
    resource_id: uuid.UUID
    name: str
    total: int
    reserved: int
    available: int
    required_per_unit: int
    requested: int
    sufficient: bool


class AvailabilityCheckResponse(BaseModel):
    available: bool
    start_at: datetime
    end_at: datetime
    requested_units: int
    max_bookable_units: int
    resources: list[ResourceAvailability]
    reason: str | None = None


class AvailabilitySlot(BaseModel):
    start_at: datetime
    end_at: datetime
    max_bookable_units: int
    available: bool
    status: str = "bookable_online"
    rates: list["AvailabilityRate"] = Field(default_factory=list)


class AvailabilityRate(BaseModel):
    rate_id: uuid.UUID
    customer_type_name: str
    seat_count: int
    available_quantity: int
    available_seats: int


class PublicCalendarSummary(BaseModel):
    id: uuid.UUID
    operator_name: str
    operator_slug: str
    calendar_name: str
    calendar_slug: str
    description: str | None
    duration_minutes: int
    base_price_minor: int
    currency: str
    departure_location_name: str | None
    departure_location_address: str | None


class PublicAvailabilityResponse(BaseModel):
    date: date
    time_zone: str
    calendar: PublicCalendarSummary
    slots: list[AvailabilitySlot]
