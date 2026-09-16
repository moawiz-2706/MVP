import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator


class OrderItemRequest(BaseModel):
    calendar_id: uuid.UUID
    start_at: datetime
    units: int = Field(gt=0, le=100_000)

    @model_validator(mode="after")
    def aware_start(self) -> "OrderItemRequest":
        if self.start_at.tzinfo is None:
            raise ValueError("start_at must include an offset")
        return self


class OrderCustomer(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)


class OrderQuoteRequest(BaseModel):
    items: list[OrderItemRequest] = Field(min_length=1, max_length=20)


class OrderCreateRequest(OrderQuoteRequest):
    customer: OrderCustomer


class QuotedItem(BaseModel):
    calendar_id: uuid.UUID
    calendar_name: str
    start_at: datetime
    end_at: datetime
    units: int
    base_price_minor: int
    line_subtotal_minor: int
    departure_location_name: str | None
    departure_location_address: str | None


class OrderQuoteResponse(BaseModel):
    currency: str
    items: list[QuotedItem]
    subtotal_minor: int
    platform_fee_and_taxes_minor: int
    customer_total_minor: int


class OrderCreateResponse(BaseModel):
    public_reference: str
    status: str
    client_secret: str | None
    access_token: str | None = None
    hold_expires_at: datetime | None
    quote: OrderQuoteResponse


class PublicOrderItem(QuotedItem):
    # Signing link for the booking's waiver; None when the operator has no waiver.
    waiver_url: str | None = None
    waiver_signed: bool = False


class PublicOrderStatus(BaseModel):
    public_reference: str
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
