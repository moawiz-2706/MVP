import uuid

from pydantic import BaseModel


class PublicLocation(BaseModel):
    name: str
    address: str


class PublicCalendar(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    duration_minutes: int
    base_price_minor: int
    currency: str
    category_id: uuid.UUID | None
    category_name: str | None
    category_slug: str | None
    category_color: str | None
    location: PublicLocation | None


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
