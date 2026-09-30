"""Regression tests for account-level outgoing message customization."""

import os

import pytest
from sqlalchemy import select

from app.core.exceptions import ConflictError
from app.models.entities import BookingOrder, MessageTemplate, OutboxJob
from app.services.booking_lifecycle_service import BookingLifecycleService
from app.services.ghl_email_service import GHLEmailService
from app.services.message_template_service import (
    MessageTemplateError,
    MessageTemplateService,
    default_render,
)
from tests.test_waivers_integration import _booking, _calendar, _operator


def test_default_confirmation_template_renders_safe_text() -> None:
    rendered = default_render(
        "booking_confirmation",
        {
            "operator_name": "PGA & Co",
            "customer_first_name": "Ada <script>",
            "public_reference": "PGA-1",
            "booking_details": "Sunset Cruise\nDate: September 30, 2026",
            "payment_summary": "Total Paid: USD 10.00",
        },
    )
    assert "Ada <script>" in rendered.body
    assert "&lt;script&gt;" in rendered.html
    assert "PGA-1" in rendered.body


def test_unknown_merge_field_is_rejected() -> None:
    with pytest.raises(MessageTemplateError, match="Unsupported merge field"):
        MessageTemplateService.preview("booking_confirmation", "{{not_allowed}}", "Hello")


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)
def test_account_template_is_saved_rendered_and_reset(db) -> None:
    operator = _operator(db)
    service = MessageTemplateService(db, operator.id)
    saved = service.save(
        "booking_confirmation",
        enabled=True,
        subject="Welcome {{customer_first_name}}",
        body="Hello {{customer_first_name}} from {{operator_name}}",
        user_id=None,
    )
    assert saved["is_custom"] is True
    rendered = service.render(
        "booking_confirmation",
        {"customer_first_name": "Calvin", "operator_name": "PGA"},
    )
    assert rendered.subject == "Welcome Calvin"
    assert rendered.body == "Hello Calvin from PGA"
    assert db.scalar(select(MessageTemplate).where(MessageTemplate.operator_id == operator.id)) is not None

    service.reset("booking_confirmation")
    assert db.scalar(select(MessageTemplate).where(MessageTemplate.operator_id == operator.id)) is None
    assert service.render("booking_confirmation", {"operator_name": "PGA", "customer_first_name": "Calvin"}).subject.startswith("Booking Confirmation")


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)
def test_custom_confirmation_is_delivered_through_ghl(ghl, db) -> None:
    operator = _operator(db)
    calendar = _calendar(db, operator)
    booking = _booking(db, operator, calendar)
    order = db.get(BookingOrder, booking.booking_order_id)
    assert order is not None
    order.ghl_contact_id = "contact-existing"
    db.commit()
    MessageTemplateService(db, operator.id).save(
        "booking_confirmation",
        enabled=True,
        subject="You are booked, {{customer_first_name}}",
        body="Custom confirmation for {{calendar_name}} / {{public_reference}}",
        user_id=None,
    )

    GHLEmailService(db, operator.id).send(order.id)
    message = next(payload for method, path, payload in ghl if path == "/conversations/messages")
    assert message["subject"] == "You are booked, Calvin"
    assert "Custom confirmation for Sunset Cruise" in message["message"]


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)
def test_cancellation_enqueues_customizable_customer_message(db) -> None:
    operator = _operator(db)
    calendar = _calendar(db, operator)
    booking = _booking(db, operator, calendar)
    result = BookingLifecycleService(db, operator.id).cancel(
        booking.id,
        force=True,
        reason="Customer request",
    )
    assert result["status"] == "cancelled"
    job = db.scalar(
        select(OutboxJob).where(
            OutboxJob.booking_order_id == booking.booking_order_id,
            OutboxJob.job_type == "ghl_booking_cancellation_email",
        )
    )
    assert job is not None
    assert job.payload["reason"] == "Customer request"
