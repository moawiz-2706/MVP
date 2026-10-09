from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

NotificationType = Literal[
    "booking_staff",
    "calendar_availability",
    "calendar_resources",
    "ghl_sync_failed",
]


class NotificationItem(BaseModel):
    id: str
    type: NotificationType
    title: str
    description: str
    action_label: str
    calendar_id: uuid.UUID
    calendar_name: str
    booking_id: uuid.UUID | None = None
    customer_name: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    required_roles: list[str] = Field(default_factory=list)
    missing_roles: list[str] = Field(default_factory=list)
    order_id: uuid.UUID | None = None
    sync_run_id: uuid.UUID | None = None
    sync_attempts: int | None = None
    error_code: str | None = None


class NotificationsResponse(BaseModel):
    items: list[NotificationItem]
    pending_count: int
    generated_at: datetime
