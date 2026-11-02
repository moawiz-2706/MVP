from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WorkflowTriggerSubscriptionRead(BaseModel):
    """A HighLevel workflow using the trigger. The execution URL is never exposed."""

    id: uuid.UUID
    trigger_key: str
    trigger_version: str | None = None
    ghl_workflow_id: str
    status: str
    filters: list[Any] = Field(default_factory=list)
    last_callback_event: str
    last_callback_at: datetime
    created_at: datetime


class WorkflowTriggerDeliveryRead(BaseModel):
    ghl_workflow_id: str
    status: str
    attempt_count: int
    last_http_status: int | None = None
    last_error: str | None = None
    last_attempt_at: datetime | None = None
    delivered_at: datetime | None = None


class WorkflowTriggerEventRead(BaseModel):
    id: uuid.UUID
    event_type: str
    event_id: str
    status: str
    occurred_at: datetime
    delivered_at: datetime | None = None
    last_error: str | None = None
    deliveries: list[WorkflowTriggerDeliveryRead] = Field(default_factory=list)


class WorkflowTriggerOrderStatus(BaseModel):
    booking_order_id: uuid.UUID
    # False until GHL_WORKFLOW_TRIGGER_ENABLED is set; the UI then hides the section.
    enabled: bool = True
    events: list[WorkflowTriggerEventRead] = Field(default_factory=list)


class WorkflowTriggerRetryResponse(WorkflowTriggerOrderStatus):
    requeued: int
