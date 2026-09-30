from __future__ import annotations

import html
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import MessageTemplate


MESSAGE_EVENT_TYPES = (
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
)

EVENT_LABELS = {
    "booking_confirmation": "Booking confirmation",
    "booking_cancellation": "Booking cancellation",
    "weather_cancellation": "Weather cancellation",
    "booking_reschedule": "Booking reschedule",
    "booking_reminder_day_before": "Customer reminder — day before",
    "booking_reminder_same_day": "Customer reminder — same day",
    "staff_assignment": "Staff assignment",
    "staff_unassignment": "Staff removal",
    "staff_reminder_day_before": "Staff reminder — day before",
    "staff_reminder_same_day": "Staff reminder — same day",
}

PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z][a-zA-Z0-9_]*)\s*}}")

GLOBAL_VARIABLES = {
    "operator_name",
    "operator_slug",
    "customer_first_name",
    "customer_last_name",
    "customer_email",
    "public_reference",
    "calendar_name",
    "booking_details",
    "payment_summary",
    "start_date",
    "start_time",
    "end_time",
    "time_zone",
    "location_name",
    "location_address",
    "units",
    "currency",
    "booking_total",
    "cancel_reason",
    "adjustment_outcome",
    "previous_start",
    "payment_outcome",
    "waiver_url",
    "staff_name",
    "staff_role",
    "guests_booked",
    "when",
}


@dataclass(frozen=True)
class TemplateDefinition:
    subject: str
    body: str


@dataclass(frozen=True)
class RenderedMessage:
    enabled: bool
    subject: str
    body: str
    html: str


DEFAULT_TEMPLATES: dict[str, TemplateDefinition] = {
    "booking_confirmation": TemplateDefinition(
        "Booking Confirmation - {{operator_name}}",
        "Hi {{customer_first_name}},\n\nYour booking is confirmed.\nOrder: {{public_reference}}\n\n{{booking_details}}\n\nPayment:\n{{payment_summary}}\n\nThank you,\n{{operator_name}}",
    ),
    "booking_cancellation": TemplateDefinition(
        "Booking Cancelled - {{operator_name}}",
        "Hi {{customer_first_name}},\n\nYour booking has been cancelled.\n\n{{booking_details}}\n\nReason: {{cancel_reason}}\n{{adjustment_outcome}}\n\nPlease contact {{operator_name}} if you have any questions.",
    ),
    "weather_cancellation": TemplateDefinition(
        "Weather Cancellation - {{operator_name}}",
        "Hi {{customer_first_name}},\n\nYour booking has been cancelled because of weather or operating conditions.\n\n{{booking_details}}\n\nReason: {{cancel_reason}}\n{{adjustment_outcome}}\n\nWe are sorry for the change and appreciate your understanding.\n{{operator_name}}",
    ),
    "booking_reschedule": TemplateDefinition(
        "Booking Rescheduled - {{operator_name}}",
        "Hi {{customer_first_name}},\n\nYour booking has been rescheduled.\n\n{{booking_details}}\nPrevious time: {{previous_start}}\nPayment outcome: {{payment_outcome}}\n\nThank you,\n{{operator_name}}",
    ),
    "booking_reminder_day_before": TemplateDefinition(
        "Reminder: your booking is tomorrow - {{operator_name}}",
        "Hi {{customer_first_name}},\n\nThis is a reminder that your booking is tomorrow.\n\n{{booking_details}}\n\nSee you soon,\n{{operator_name}}",
    ),
    "booking_reminder_same_day": TemplateDefinition(
        "Reminder: your booking is today - {{operator_name}}",
        "Hi {{customer_first_name}},\n\nThis is a reminder that your booking is today.\n\n{{booking_details}}\n\nSee you soon,\n{{operator_name}}",
    ),
    "staff_assignment": TemplateDefinition(
        "You're scheduled: {{calendar_name}} on {{start_date}} - {{operator_name}}",
        "Hi {{staff_name}},\n\nYou've been assigned to {{calendar_name}}{{staff_role}}.\n\n{{booking_details}}\nGuests booked so far: {{guests_booked}}\n\nThanks,\n{{operator_name}}",
    ),
    "staff_unassignment": TemplateDefinition(
        "Schedule change: {{calendar_name}} on {{start_date}} - {{operator_name}}",
        "Hi {{staff_name}},\n\nYou're no longer scheduled for {{calendar_name}}{{staff_role}}. No action is needed.\n\n{{booking_details}}\n\nThanks,\n{{operator_name}}",
    ),
    "staff_reminder_day_before": TemplateDefinition(
        "Reminder: {{calendar_name}} {{when}} at {{start_time}} - {{operator_name}}",
        "Hi {{staff_name}},\n\nA reminder that you're working {{calendar_name}}{{staff_role}} tomorrow.\n\n{{booking_details}}\nGuests booked so far: {{guests_booked}}\n\nThanks,\n{{operator_name}}",
    ),
    "staff_reminder_same_day": TemplateDefinition(
        "Reminder: {{calendar_name}} {{when}} at {{start_time}} - {{operator_name}}",
        "Hi {{staff_name}},\n\nA reminder that you're working {{calendar_name}}{{staff_role}} today.\n\n{{booking_details}}\nGuests booked so far: {{guests_booked}}\n\nThanks,\n{{operator_name}}",
    ),
}


class MessageTemplateError(ValueError):
    pass


def _placeholders(value: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(value))


def validate_template(event_type: str, subject: str, body: str) -> None:
    if event_type not in MESSAGE_EVENT_TYPES:
        raise MessageTemplateError("Unsupported message event type")
    if not subject.strip():
        raise MessageTemplateError("Subject cannot be blank")
    if not body.strip():
        raise MessageTemplateError("Message body cannot be blank")
    if "\r" in subject or "\n" in subject:
        raise MessageTemplateError("Subject cannot contain line breaks")
    unknown = (_placeholders(subject) | _placeholders(body)) - GLOBAL_VARIABLES
    if unknown:
        names = ", ".join(sorted(unknown))
        raise MessageTemplateError(f"Unsupported merge field(s): {names}")
    # A brace that looks like an unclosed merge field is almost always a typo.
    for value, label in ((subject, "Subject"), (body, "Message body")):
        if value.count("{{") != value.count("}}"):
            raise MessageTemplateError(f"{label} contains an unclosed merge field")


def render_text(template: str, context: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        value = context.get(match.group(1), "")
        return "" if value is None else str(value)

    return PLACEHOLDER_RE.sub(replace, template)


def text_to_html(body: str, context: dict[str, Any] | None = None) -> str:
    paragraphs = []
    for paragraph in body.split("\n\n"):
        escaped = html.escape(paragraph).replace("\n", "<br>")
        waiver_url = (context or {}).get("waiver_url")
        if waiver_url:
            safe_url = html.escape(str(waiver_url), quote=True)
            escaped = escaped.replace(
                safe_url,
                f'<a href="{safe_url}">{html.escape(str(waiver_url))}</a>',
            )
        if escaped.strip():
            paragraphs.append(f"<p>{escaped}</p>")
    return "".join(paragraphs)


def render_definition(definition: TemplateDefinition, context: dict[str, Any], *, enabled: bool = True) -> RenderedMessage:
    subject = render_text(definition.subject, context).strip()
    body = render_text(definition.body, context).strip()
    return RenderedMessage(enabled=enabled, subject=subject, body=body, html=text_to_html(body, context))


def default_render(event_type: str, context: dict[str, Any]) -> RenderedMessage:
    definition = DEFAULT_TEMPLATES[event_type]
    return render_definition(definition, context)


class MessageTemplateService:
    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id

    @staticmethod
    def event_type(event_type: str) -> str:
        if event_type not in MESSAGE_EVENT_TYPES:
            raise MessageTemplateError("Unsupported message event type")
        return event_type

    def _row(self, event_type: str) -> MessageTemplate | None:
        return self.db.scalar(
            select(MessageTemplate).where(
                MessageTemplate.operator_id == self.operator_id,
                MessageTemplate.event_type == self.event_type(event_type),
            )
        )

    def definition(self, event_type: str) -> tuple[TemplateDefinition, bool, bool]:
        event_type = self.event_type(event_type)
        row = self._row(event_type)
        if row is None:
            return DEFAULT_TEMPLATES[event_type], True, False
        try:
            validate_template(event_type, row.subject_template, row.body_template)
        except MessageTemplateError:
            # A malformed template must never make a booking notification fail.
            return DEFAULT_TEMPLATES[event_type], row.enabled, True
        return TemplateDefinition(row.subject_template, row.body_template), row.enabled, True

    def render(self, event_type: str, context: dict[str, Any]) -> RenderedMessage:
        definition, enabled, _ = self.definition(event_type)
        return render_definition(definition, context, enabled=enabled)

    def list_effective(self, context_by_event: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        context_by_event = context_by_event or {}
        rows = {
            row.event_type: row
            for row in self.db.scalars(
                select(MessageTemplate).where(MessageTemplate.operator_id == self.operator_id)
            )
        }
        result = []
        for event_type in MESSAGE_EVENT_TYPES:
            row = rows.get(event_type)
            default = DEFAULT_TEMPLATES[event_type]
            subject = row.subject_template if row else default.subject
            body = row.body_template if row else default.body
            enabled = row.enabled if row else True
            try:
                validate_template(event_type, subject, body)
            except MessageTemplateError:
                subject, body = default.subject, default.body
            context = context_by_event.get(event_type) or self.preview_context(event_type)
            rendered = render_definition(TemplateDefinition(subject, body), context, enabled=enabled)
            result.append(
                {
                    "event_type": event_type,
                    "label": EVENT_LABELS[event_type],
                    "enabled": enabled,
                    "subject_template": subject,
                    "body_template": body,
                    "is_custom": row is not None,
                    "available_variables": sorted(GLOBAL_VARIABLES),
                    "preview_subject": rendered.subject,
                    "preview_body": rendered.body,
                }
            )
        return result

    def save(self, event_type: str, *, enabled: bool, subject: str, body: str, user_id: uuid.UUID | None) -> dict[str, Any]:
        event_type = self.event_type(event_type)
        validate_template(event_type, subject, body)
        row = self._row(event_type)
        if row is None:
            row = MessageTemplate(
                operator_id=self.operator_id,
                event_type=event_type,
                enabled=enabled,
                subject_template=subject.strip(),
                body_template=body.strip(),
                updated_by_user_id=user_id,
            )
            self.db.add(row)
        else:
            row.enabled = enabled
            row.subject_template = subject.strip()
            row.body_template = body.strip()
            row.updated_by_user_id = user_id
        self.db.commit()
        return self.list_effective()[MESSAGE_EVENT_TYPES.index(event_type)]

    def reset(self, event_type: str) -> None:
        row = self._row(event_type)
        if row is not None:
            self.db.delete(row)
            self.db.commit()

    @staticmethod
    def preview_context(event_type: str) -> dict[str, Any]:
        common = {
            "operator_name": "Punta Gorda Adventures",
            "operator_slug": "punta-gorda-adventures",
            "customer_first_name": "Alex",
            "customer_last_name": "Morgan",
            "customer_email": "alex@example.com",
            "public_reference": "PGA-12345",
            "calendar_name": "Sunset Dolphin Tour",
            "booking_details": "Sunset Dolphin Tour\nDate: September 30, 2026\nTime: 10:00 AM - 12:00 PM EDT\nQuantity: 2\nLocation: Fishermen's Village",
            "payment_summary": "Subtotal: USD 180.00\nPlatform Fee & Taxes: USD 18.00\nTotal Paid: USD 198.00",
            "start_date": "September 30, 2026",
            "start_time": "10:00 AM",
            "end_time": "12:00 PM",
            "time_zone": "America/New_York",
            "location_name": "Fishermen's Village",
            "location_address": "1200 W Retta Esplanade, Punta Gorda, FL",
            "units": "2",
            "currency": "USD",
            "booking_total": "198.00",
            "cancel_reason": "Customer request",
            "adjustment_outcome": "A refund of USD 198.00 has been initiated.",
            "previous_start": "September 29, 2026 at 10:00 AM EDT",
            "payment_outcome": "No payment adjustment was required.",
            "waiver_url": "https://example.com/waiver/demo-token",
            "staff_name": "Jordan Lee",
            "staff_role": " as Captain",
            "guests_booked": "8",
            "when": "tomorrow",
        }
        return common

    @classmethod
    def preview(cls, event_type: str, subject: str | None, body: str | None) -> dict[str, Any]:
        event_type = cls.event_type(event_type)
        default = DEFAULT_TEMPLATES[event_type]
        subject = subject if subject is not None else default.subject
        body = body if body is not None else default.body
        validate_template(event_type, subject, body)
        rendered = render_definition(TemplateDefinition(subject, body), cls.preview_context(event_type))
        return {"subject": rendered.subject, "body": rendered.body, "html": rendered.html}
