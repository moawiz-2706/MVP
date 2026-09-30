from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.configuration import CalendarRead
from app.schemas.order import OrderCreateResponse
from app.schemas.public import PublicCustomField, PublicRate
from app.schemas.availability import PublicAvailabilityResponse


class StaffBookingContext(BaseModel):
    staff_id: uuid.UUID
    staff_name: str
    operator_name: str
    time_zone: str
    calendars: list[CalendarRead]


class StaffBookingLinkOrderResponse(OrderCreateResponse):
    pass
