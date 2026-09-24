import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.schemas.waiver import WaiverSummary


class BookingListItem(BaseModel):
    id: uuid.UUID
    booking_order_id: uuid.UUID
    public_reference: str
    calendar_id: uuid.UUID
    calendar_name: str
    category_id: uuid.UUID | None
    category_name: str | None
    category_color: str | None
    customer_name: str
    customer_email: EmailStr
    start_at: datetime
    end_at: datetime
    units: int
    status: str


class SlotStaff(BaseModel):
    id: uuid.UUID
    staff_id: uuid.UUID
    staff_name: str
    role: str | None


class SlotCalendar(BaseModel):
    """One calendar's share of a dashboard time slot."""

    calendar_id: uuid.UUID
    calendar_name: str
    category_color: str | None
    end_at: datetime
    pushed: bool
    bookings: list[BookingListItem]
    staff: list[SlotStaff]
    capacity: int | None = None
    booked_units: int = 0


class DashboardSlot(BaseModel):
    """Everything starting at one instant, grouped by calendar."""

    start_at: datetime
    calendars: list[SlotCalendar]


class BookingResourceDetail(BaseModel):
    resource_id: uuid.UUID
    name: str
    quantity: int


class BookingNoteRead(BaseModel):
    id: uuid.UUID
    author_user_id: uuid.UUID | None
    author_name: str | None
    body: str
    created_at: datetime


class BookingNoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)

    @field_validator("body", mode="before")
    @classmethod
    def strip_body(cls, value):
        return value.strip() if isinstance(value, str) else value


class BookingParticipantRead(BaseModel):
    id: uuid.UUID
    sequence: int
    first_name: str
    last_name: str
    email: EmailStr | None
    phone: str | None
    date_of_birth: date | None
    is_minor: bool
    guardian_name: str | None
    emergency_contact: dict | None
    operational_notes: str | None
    status: str
    source: str


class BookingParticipantWrite(BaseModel):
    sequence: int = Field(gt=0)
    first_name: str = Field(min_length=1, max_length=160)
    last_name: str = Field(min_length=1, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=60)
    date_of_birth: date | None = None
    is_minor: bool = False
    guardian_name: str | None = Field(default=None, max_length=160)
    emergency_contact: dict | None = None
    operational_notes: str | None = Field(default=None, max_length=2000)
    status: str = Field(default="active", pattern="^(active|cancelled|no_show)$")


class BookingDetail(BookingListItem):
    customer_phone: str | None
    marketing_opt_in: bool
    location_name: str | None
    location_address: str | None
    payment_status: str
    subtotal_minor: int
    platform_fee_and_taxes_minor: int
    customer_total_minor: int
    rate_id: uuid.UUID | None
    customer_type_name: str | None
    seat_count: int
    booking_fee_minor: int
    tax_minor: int
    line_total_minor: int
    booking_policy_version: int | None
    ghl_contact_sync_status: str
    ghl_confirmation_email_status: str
    ghl_appointment_sync_status: str
    ghl_appointment_event_id: str | None
    ghl_appointment_last_error: str | None
    resources: list[BookingResourceDetail]
    created_at: datetime
    waiver: WaiverSummary
    notes: list[BookingNoteRead]
    participants: list[BookingParticipantRead]


class BookingUpdate(BaseModel):
    start_at: datetime | None = None
    units: int | None = Field(default=None, gt=0, le=100_000)

    @model_validator(mode="after")
    def validate_change(self) -> "BookingUpdate":
        if self.start_at is not None and self.start_at.tzinfo is None:
            raise ValueError("start_at must include an offset")
        if self.start_at is None and self.units is None:
            raise ValueError("At least one field must be supplied")
        return self


class BookingNotificationItem(BaseModel):
    booking_id: uuid.UUID
    calendar_id: uuid.UUID
    calendar_name: str
    customer_name: str
    start_at: datetime
    end_at: datetime
    units: int
    status: str
    created_at: datetime
    assignment_status: str
    captain_name: str | None
    reason: str | None


class BookingNotificationsResponse(BaseModel):
    items: list[BookingNotificationItem]
    pending_count: int
