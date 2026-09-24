import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


WeatherRefundMode = Literal["full_refund", "credit", "manual_review", "no_refund"]
NoShowMode = Literal["forfeit", "partial_refund", "manual_review"]
AdjustmentAction = Literal["refund", "charge", "credit", "manual_review", "none"]


class BookingPolicyRead(BaseModel):
    calendar_id: uuid.UUID
    version: int
    cancellation_cutoff_minutes: int
    cancellation_fee_bps: int
    weather_refund_mode: WeatherRefundMode
    reschedule_cutoff_minutes: int
    reschedule_fee_minor: int
    no_show_mode: NoShowMode
    deposit_bps: int
    requires_waiver: bool
    active: bool


class BookingPolicyWrite(BaseModel):
    cancellation_cutoff_minutes: int = Field(default=0, ge=0, le=100_000)
    cancellation_fee_bps: int = Field(default=0, ge=0, le=10_000)
    weather_refund_mode: WeatherRefundMode = "full_refund"
    reschedule_cutoff_minutes: int = Field(default=0, ge=0, le=100_000)
    reschedule_fee_minor: int = Field(default=0, ge=0)
    no_show_mode: NoShowMode = "forfeit"
    deposit_bps: int = Field(default=0, ge=0, le=10_000)
    requires_waiver: bool = False


class CustomFieldDefinitionRead(BaseModel):
    id: uuid.UUID
    calendar_id: uuid.UUID | None
    key: str
    label: str
    field_type: str
    required: bool
    options: list[Any] | None
    active: bool


class CustomFieldDefinitionWrite(BaseModel):
    calendar_id: uuid.UUID | None = None
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    label: str = Field(min_length=1, max_length=160)
    field_type: Literal["text", "textarea", "number", "date", "boolean", "select"] = "text"
    required: bool = False
    options: list[Any] | None = None
    active: bool = True


class CustomerListItem(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: EmailStr
    phone: str | None
    booking_count: int
    latest_booking_at: datetime | None
    total_paid_minor: int
    ghl_contact_id: str | None


class CustomerNoteRead(BaseModel):
    id: uuid.UUID
    body: str
    author_name: str | None
    created_at: datetime


class CustomerDetail(CustomerListItem):
    notes: list[CustomerNoteRead]
    custom_fields: dict[str, Any]
    bookings: list[dict[str, Any]]


class CustomerUpdate(BaseModel):
    first_name: str = Field(min_length=1, max_length=160)
    last_name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=60)


class CustomerNoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class BookingOperationRequest(BaseModel):
    reason: str = Field(default="Operator action", min_length=1, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=160)


class BookingRescheduleRequest(BookingOperationRequest):
    start_at: datetime
    units: int | None = Field(default=None, gt=0, le=100_000)

    @model_validator(mode="after")
    def aware_start(self) -> "BookingRescheduleRequest":
        if self.start_at.tzinfo is None:
            raise ValueError("start_at must include an offset")
        return self


class BookingStatusRequest(BookingOperationRequest):
    status: Literal["confirmed", "completed", "no_show", "cancelled", "failed"]


class WeatherClosureRequest(BaseModel):
    calendar_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    reason: str = Field(min_length=1, max_length=500)
    refund_mode: WeatherRefundMode = "full_refund"

    @model_validator(mode="after")
    def valid_interval(self) -> "WeatherClosureRequest":
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None or self.start_at >= self.end_at:
            raise ValueError("A valid timezone-aware interval is required")
        return self


class BookingCustomFieldsWrite(BaseModel):
    values: dict[str, Any]


class AdjustmentSummary(BaseModel):
    action: AdjustmentAction
    amount_minor: int
    currency: str
    status: str
    reason: str


class BookingOperationResponse(BaseModel):
    booking: dict[str, Any]
    adjustment: AdjustmentSummary | None = None
    action: str = "none"


class MigrationImportCreate(BaseModel):
    provider: Literal["fareharbor"] = "fareharbor"
    source_filename: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)


class MigrationImportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    provider: str
    status: str
    source_filename: str | None
    summary: dict[str, Any] | None
    blocking_errors: int
    committed_at: datetime | None


class ReconciliationRunCreate(BaseModel):
    scope: Literal["inventory", "bookings", "payments", "waivers", "ghl_projection"]
    start_at: datetime | None = None
    end_at: datetime | None = None


class ReconciliationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    scope: str
    status: str
    summary: dict[str, Any] | None
    started_at: datetime | None
    finished_at: datetime | None
