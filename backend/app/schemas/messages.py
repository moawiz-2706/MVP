from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


MessageEventType = Literal[
    "booking_confirmation",
    "booking_cancellation",
    "weather_cancellation",
    "booking_reschedule",
    "booking_reminder_day_before",
    "booking_reminder_same_day",
    "staff_assignment",
    "staff_unassignment",
    "staff_reminder_day_before",
    "staff_reminder_same_day",
]


class MessageTemplateRead(BaseModel):
    event_type: MessageEventType
    label: str
    enabled: bool
    subject_template: str
    body_template: str
    is_custom: bool
    available_variables: list[str]
    preview_subject: str
    preview_body: str


class MessageTemplateUpdate(BaseModel):
    enabled: bool = True
    subject_template: str = Field(min_length=1, max_length=240)
    body_template: str = Field(min_length=1, max_length=20_000)


class MessageTemplatePreviewRequest(BaseModel):
    event_type: MessageEventType
    subject_template: str | None = Field(default=None, max_length=240)
    body_template: str | None = Field(default=None, max_length=20_000)


class MessageTemplatePreviewResponse(BaseModel):
    subject: str
    body: str
    html: str
