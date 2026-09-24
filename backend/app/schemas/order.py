import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator


class OrderItemRequest(BaseModel):
    calendar_id: uuid.UUID
    start_at: datetime
    rate_id: uuid.UUID | None = None
    quantity: int | None = Field(default=None, gt=0, le=100_000)
    # Legacy clients may continue sending units until the customer-type UI is live.
    units: int | None = Field(default=None, gt=0, le=100_000)

    @model_validator(mode="after")
    def aware_start(self) -> "OrderItemRequest":
        if self.start_at.tzinfo is None:
            raise ValueError("start_at must include an offset")
        if self.quantity is None and self.units is None:
            raise ValueError("quantity is required")
        if self.quantity is not None and self.units is not None and self.quantity != self.units:
            raise ValueError("quantity and units must match when both are supplied")
        return self

    @property
    def requested_quantity(self) -> int:
        return self.quantity if self.quantity is not None else self.units  # type: ignore[return-value]


class OrderCustomer(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    marketing_opt_in: bool = False


class OrderQuoteRequest(BaseModel):
    items: list[OrderItemRequest] = Field(min_length=1, max_length=20)


class OrderCreateRequest(OrderQuoteRequest):
    customer: OrderCustomer
    custom_fields: dict[str, object] = Field(default_factory=dict)


class QuotedItem(BaseModel):
    calendar_id: uuid.UUID
    calendar_name: str
    start_at: datetime
    end_at: datetime
    units: int
    base_price_minor: int
    line_subtotal_minor: int
    rate_id: uuid.UUID | None = None
    customer_type_name: str | None = None
    customer_type_note: str | None = None
    seat_count: int = 1
    unit_price_minor: int | None = None
    booking_fee_minor: int = 0
    tax_minor: int = 0
    line_total_minor: int | None = None
    resources: list[dict] = Field(default_factory=list)
    departure_location_name: str | None = None
    departure_location_address: str | None = None


class OrderQuoteResponse(BaseModel):
    currency: str
    items: list[QuotedItem]
    subtotal_minor: int
    platform_fee_and_taxes_minor: int
    customer_total_minor: int
    booking_fee_minor: int = 0
    tax_minor: int = 0


class OrderCreateResponse(BaseModel):
    public_reference: str
    status: str
    client_secret: str | None
    access_token: str | None = None
    hold_expires_at: datetime | None
    quote: OrderQuoteResponse


class PublicOrderItem(QuotedItem):
    booking_id: uuid.UUID
    calendar_slug: str
    # Signing link for the booking's waiver; None when the operator has no waiver.
    waiver_url: str | None = None
    waiver_signed: bool = False


class PublicOrderStatus(BaseModel):
    public_reference: str
    operator_slug: str
    access_token: str | None = None
    status: str
    # Operator IANA zone: customer-facing times are always rendered in it.
    time_zone: str
    payment_status: str
    confirmed: bool
    customer_name: str
    currency: str
    subtotal_minor: int
    platform_fee_and_taxes_minor: int
    customer_total_minor: int
    items: list[PublicOrderItem]


class PublicRescheduleRequest(BaseModel):
    start_at: datetime
    units: int | None = Field(default=None, gt=0, le=100_000)

    @model_validator(mode="after")
    def aware_start(self) -> "PublicRescheduleRequest":
        if self.start_at.tzinfo is None:
            raise ValueError("start_at must include an offset")
        return self


class PublicRescheduleResponse(BaseModel):
    booking_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    status: str
    payment_outcome: str
