"""Pure-logic tests for waiver input rules, age maths, and waiver links in emails."""

import base64
import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.models.entities import Booking, BookingOrder, Operator
from app.schemas.waiver import WaiverSettings, WaiverSignRequest
from app.services.ghl_email_service import GHLEmailService, booking_reminder_content, staff_content
from app.services.waiver_service import age_on

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode()
URL = "https://passport.example/waiver/abc123"


def _request(**overrides):
    body = {
        "signer": {
            "first_name": " Calvin ",
            "last_name": "Schofield",
            "email": "calvin@example.com",
            "phone": "+19415550100",
            "date_of_birth": "1991-07-16",
        },
        "address": {"street": "4824 Fairway Dr S", "city": "Punta Gorda", "state": "FL", "postal_code": "33982", "country": "USA"},
        "participants": [{"first_name": "Azaria", "last_name": "Hart", "date_of_birth": "2015-02-10"}],
        "agreed": True,
        "signature_png": PNG,
    }
    body.update(overrides)
    return body


def test_valid_request_parses_and_trims_names() -> None:
    request = WaiverSignRequest(**_request())
    assert request.signer.first_name == "Calvin"
    assert request.participants[0].date_of_birth == date(2015, 2, 10)


def test_signer_must_agree() -> None:
    with pytest.raises(ValidationError, match="agree"):
        WaiverSignRequest(**_request(agreed=False))


@pytest.mark.parametrize(
    "signature",
    [
        "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff").decode(),  # not PNG
        "data:image/png;base64,***not-base64***",
        "data:image/png;base64," + base64.b64encode(b"GIF89a").decode(),  # wrong magic bytes
    ],
)
def test_signature_must_be_a_real_png(signature) -> None:
    with pytest.raises(ValidationError):
        WaiverSignRequest(**_request(signature_png=signature))


def test_blank_settings_mean_unset() -> None:
    settings = WaiverSettings(waiver_title="  ", waiver_text="\n\n", waiver_website="example.com")
    assert settings.waiver_title is None and settings.waiver_text is None
    assert settings.waiver_website == "example.com"


def test_age_turns_over_on_the_birthday() -> None:
    assert age_on(date(2008, 9, 15), date(2026, 9, 14)) == 17
    assert age_on(date(2008, 9, 15), date(2026, 9, 15)) == 18


def _operator() -> Operator:
    return Operator(name="Punta Gorda Adventures", slug="pga", time_zone="America/New_York", ghl_location_id="loc")


def _booking() -> Booking:
    return Booking(
        id=uuid.uuid4(),
        calendar_name_snapshot="Sunset Cruise",
        start_at=datetime(2026, 9, 15, 22, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 16, 0, 0, tzinfo=UTC),
        units=2,
    )


def test_confirmation_email_carries_each_bookings_waiver_link() -> None:
    order = BookingOrder(
        customer_first_name="Ada",
        public_reference="RM-1",
        currency="usd",
        subtotal_minor=10000,
        platform_fee_and_taxes_minor=1300,
        customer_total_minor=11300,
    )
    booking = _booking()
    plain, markup = GHLEmailService._content(order, _operator(), [booking], {booking.id: URL})
    assert f"Sign your waiver before you arrive: {URL}" in plain
    assert f'href="{URL}"' in markup


def test_reminder_includes_waiver_link_only_when_given() -> None:
    order = BookingOrder(customer_first_name="Ada", public_reference="RM-1")
    _, plain, markup = booking_reminder_content(order, _operator(), _booking(), "day_before", URL)
    assert URL in plain and f'href="{URL}"' in markup
    _, plain, _ = booking_reminder_content(order, _operator(), _booking(), "day_before")
    assert "waiver" not in plain


def test_staff_removal_email_wording() -> None:
    subject, plain, _ = staff_content(
        "unassigned",
        staff_name="Sam Captain",
        role="Captain",
        calendar_name="Sunset Cruise",
        start=datetime(2026, 9, 15, 18, 0, tzinfo=ZoneInfo("America/New_York")),
        end=datetime(2026, 9, 15, 20, 0, tzinfo=ZoneInfo("America/New_York")),
        location=None,
        guests=None,
        operator_name="PGA",
    )
    assert subject == "Schedule change: Sunset Cruise on Sep 15 - PGA"
    assert "no longer scheduled for Sunset Cruise as Captain" in plain
    assert "Guests booked" not in plain
