import uuid

from pydantic import BaseModel, Field


class PublicLocation(BaseModel):
    name: str
    address: str


class PublicBookingPolicy(BaseModel):
    cancellation_cutoff_minutes: int = 0
    cancellation_fee_bps: int = 0
    weather_refund_mode: str = "manual_review"
    reschedule_cutoff_minutes: int = 0
    reschedule_fee_minor: int = 0
    no_show_mode: str = "forfeit"
    requires_waiver: bool = False


class PublicCalendar(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    headline: str | None = None
    description: str | None
    booking_instructions: str | None = None
    hero_image_url: str | None = None
    gallery_image_urls: list[str] = Field(default_factory=list)
    duration_minutes: int
    base_price_minor: int
    currency: str
    category_id: uuid.UUID | None
    category_name: str | None
    category_slug: str | None
    category_color: str | None
    location: PublicLocation | None
    public_booking_mode: str = "online"
    booking_cutoff_minutes: int | None = None
    call_to_book_phone: str | None = None
    booking_policy: PublicBookingPolicy | None = None


class PublicRateResource(BaseModel):
    resource_id: uuid.UUID
    name: str
    quantity_per_unit: int
    total_quantity: int


class PublicRate(BaseModel):
    id: uuid.UUID
    customer_type_name: str
    customer_type_plural_name: str
    note: str | None
    seat_count: int
    price_minor: int
    booking_fee_bps: int
    tax_bps: int
    resources: list[PublicRateResource]


class PublicCustomField(BaseModel):
    id: uuid.UUID
    key: str
    label: str
    field_type: str
    required: bool
    options: list | None


class PublicOperatorCatalog(BaseModel):
    name: str
    slug: str
    time_zone: str
    calendars: list[PublicCalendar]


class PublicCategoryPage(BaseModel):
    operator_name: str
    operator_slug: str
    time_zone: str
    category_name: str
    category_slug: str
    calendars: list[PublicCalendar]
