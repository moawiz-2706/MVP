import html
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Booking,
    BookingOrder,
    Calendar,
    DepartureLocation,
    Operator,
    OperatorSettings,
    Staff,
    StaffAssignment,
)
from app.services.ghl_client import GHLClient
from app.services.ghl_contact_service import GHLContactService
from app.services.reminder_service import reminder_still_due
from app.services.waiver_service import WaiverService
from app.utils.timezone import require_timezone

WHEN = {"day_before": "tomorrow", "same_day": "today"}
WAIVER_LINK_LABEL = "Sign your waiver before you arrive"


def _money(value: int, currency: str) -> str:
    return f"{currency.upper()} {Decimal(value) / Decimal(100):,.2f}"


def _clock(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def _when_lines(start: datetime, end: datetime) -> list[str]:
    """Date and time lines for values already converted to the operator zone."""
    return [
        f"Date: {start:%B %d, %Y}",
        f"Time: {_clock(start)} - {_clock(end)} {start.strftime('%Z')}",
    ]


def _link_html(label: str, url: str) -> str:
    return f'<p><a href="{html.escape(url, quote=True)}">{html.escape(label)}</a></p>'


def _render(
    greeting: str,
    intro: str,
    title: str,
    lines: list[str],
    closing: str,
    sign_off: str,
    link: tuple[str, str] | None = None,
) -> tuple[str, str]:
    """Plain-text and HTML bodies from the same content, escaping every value."""
    plain = [greeting, "", intro, "", title, *lines]
    if link:
        plain.extend(["", f"{link[0]}: {link[1]}"])
    plain.extend(["", closing, sign_off])
    markup = (
        f"<p>{html.escape(greeting)}</p><p>{html.escape(intro)}</p>"
        f"<section><h3>{html.escape(title)}</h3><p>"
        + "<br>".join(html.escape(line) for line in lines)
        + "</p></section>"
        + (_link_html(*link) if link else "")
        + f"<p>{html.escape(closing)}<br>{html.escape(sign_off)}</p>"
    )
    return "\n".join(plain), markup


def booking_reminder_content(
    order: BookingOrder,
    operator: Operator,
    booking: Booking,
    kind: str,
    waiver_url: str | None = None,
) -> tuple[str, str, str]:
    zone = require_timezone(operator.time_zone)
    lines = _when_lines(booking.start_at.astimezone(zone), booking.end_at.astimezone(zone))
    lines.append(f"Quantity: {booking.units}")
    if booking.departure_location_name_snapshot:
        lines.append(f"Location: {booking.departure_location_name_snapshot}")
    if booking.departure_location_address_snapshot:
        lines.append(f"Address: {booking.departure_location_address_snapshot}")
    lines.append(f"Order: {order.public_reference}")
    subject = f"Reminder: your booking is {WHEN[kind]} - {operator.name}"
    plain, markup = _render(
        f"Hi {order.customer_first_name},",
        f"This is a reminder that your booking is {WHEN[kind]}.",
        booking.calendar_name_snapshot,
        lines,
        "See you soon,",
        operator.name,
        link=(WAIVER_LINK_LABEL, waiver_url) if waiver_url else None,
    )
    return subject, plain, markup


def staff_content(
    kind: str,
    *,
    staff_name: str,
    role: str | None,
    calendar_name: str,
    start: datetime,
    end: datetime,
    location: DepartureLocation | None,
    guests: int | None,
    operator_name: str,
) -> tuple[str, str, str]:
    """Staff email: "assigned", "unassigned", or a "day_before"/"same_day" reminder.

    `start`/`end` must already be in the operator's zone.
    """
    lines = _when_lines(start, end)
    if role:
        lines.append(f"Role: {role}")
    if location:
        lines.extend([f"Location: {location.name}", f"Address: {location.address}"])
    if guests is not None:
        lines.append(f"Guests booked so far: {guests}")
    first_name = staff_name.split()[0] if staff_name.split() else staff_name
    as_role = f" as {role}" if role else ""
    if kind == "assigned":
        subject = f"You're scheduled: {calendar_name} on {start:%b %d} - {operator_name}"
        intro = f"You've been assigned to {calendar_name}{as_role}."
    elif kind == "unassigned":
        subject = f"Schedule change: {calendar_name} on {start:%b %d} - {operator_name}"
        intro = f"You're no longer scheduled for {calendar_name}{as_role}. No action is needed."
    else:
        subject = f"Reminder: {calendar_name} {WHEN[kind]} at {_clock(start)} - {operator_name}"
        intro = f"A reminder that you're working {calendar_name}{as_role} {WHEN[kind]}."
    plain, markup = _render(f"Hi {first_name},", intro, calendar_name, lines, "Thanks,", operator_name)
    return subject, plain, markup


class GHLEmailService:
    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id
        self.client = GHLClient(operator_id, db)

    def _deliver(
        self,
        contact_id: str,
        subject: str,
        plain: str,
        markup: str,
        settings: OperatorSettings | None,
    ) -> dict[str, Any]:
        payload = {
            "type": "Email",
            "contactId": contact_id,
            "subject": subject,
            "html": markup,
            "message": plain,
        }
        if settings and settings.confirmation_email_from:
            payload["emailFrom"] = settings.confirmation_email_from
        return self.client.request(
            "POST", "/conversations/messages", version="2021-04-15", json=payload
        )

    def send(self, order_id: uuid.UUID) -> None:
        row = self.db.execute(
            select(BookingOrder, Operator, OperatorSettings)
            .join(Operator, Operator.id == BookingOrder.operator_id)
            .outerjoin(OperatorSettings, OperatorSettings.operator_id == Operator.id)
            .where(
                BookingOrder.id == order_id,
                BookingOrder.operator_id == self.operator_id,
            )
        ).one_or_none()
        if row is None:
            raise RuntimeError("GHL email order not found")
        order, operator, settings = row
        if settings and not settings.confirmation_email_enabled:
            order.ghl_confirmation_email_status = "disabled"
            self.db.commit()
            return
        if not order.ghl_contact_id:
            raise RuntimeError("GHL Contact must be synchronized before email")
        bookings = list(
            self.db.scalars(
                select(Booking)
                .where(Booking.booking_order_id == order.id)
                .order_by(Booking.start_at)
            )
        )
        waiver_links = WaiverService(self.db).links_for_bookings(bookings)
        subject_base = settings.confirmation_email_subject if settings else "Booking Confirmation"
        subject = f"{subject_base} - {operator.name}"
        plain, markup = self._content(order, operator, bookings, waiver_links)
        response = self._deliver(order.ghl_contact_id, subject, plain, markup, settings)
        order.ghl_conversation_id = response.get("conversationId")
        order.ghl_message_id = response.get("messageId")
        order.ghl_email_message_id = response.get("emailMessageId")
        order.ghl_confirmation_email_status = "sent"
        self.db.commit()

    def send_booking_reminder(self, booking_id: uuid.UUID, kind: str) -> None:
        """Customer reminder. A no-op if the booking was cancelled or the day has passed."""
        row = self.db.execute(
            select(Booking, BookingOrder, Operator, OperatorSettings)
            .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
            .join(Operator, Operator.id == Booking.operator_id)
            .outerjoin(OperatorSettings, OperatorSettings.operator_id == Operator.id)
            .where(Booking.id == booking_id, Booking.operator_id == self.operator_id)
        ).one_or_none()
        if row is None:
            return
        booking, order, operator, settings = row
        if (
            booking.status != "confirmed"
            or (settings and not settings.confirmation_email_enabled)
            or not reminder_still_due(kind, booking.start_at, datetime.now(UTC), operator.time_zone)
        ):
            return
        contact_id = order.ghl_contact_id or GHLContactService(self.db, self.operator_id).sync(order.id)
        waiver_link = WaiverService(self.db).links_for_bookings([booking]).get(booking.id)
        subject, plain, markup = booking_reminder_content(order, operator, booking, kind, waiver_link)
        self._deliver(contact_id, subject, plain, markup, settings)

    def send_staff_assigned(self, assignment_id: uuid.UUID) -> None:
        self._send_staff(assignment_id, "assigned")

    def send_staff_reminder(self, assignment_id: uuid.UUID, kind: str) -> None:
        self._send_staff(assignment_id, kind)

    def _send_staff(self, assignment_id: uuid.UUID, kind: str) -> None:
        row = self.db.execute(
            select(StaffAssignment, Staff, Calendar, Operator, OperatorSettings, DepartureLocation)
            .join(Staff, Staff.id == StaffAssignment.staff_id)
            .join(Calendar, Calendar.id == StaffAssignment.calendar_id)
            .join(Operator, Operator.id == StaffAssignment.operator_id)
            .outerjoin(OperatorSettings, OperatorSettings.operator_id == Operator.id)
            .outerjoin(DepartureLocation, DepartureLocation.id == Calendar.departure_location_id)
            .where(
                StaffAssignment.id == assignment_id,
                StaffAssignment.operator_id == self.operator_id,
            )
        ).one_or_none()
        if row is None:  # unassigned since the job was queued
            return
        assignment, staff, calendar, operator, settings, location = row
        now = datetime.now(UTC)
        if staff.deleted_at is not None or not staff.is_active or not staff.email:
            return
        if kind == "assigned":
            if assignment.start_at <= now:
                return
        elif not reminder_still_due(kind, assignment.start_at, now, operator.time_zone):
            return
        contact_id = staff.ghl_contact_id or GHLContactService(self.db, self.operator_id).sync_staff(
            staff.id
        )
        if not contact_id:
            return
        guests = self.db.scalar(
            select(func.coalesce(func.sum(Booking.units), 0)).where(
                Booking.calendar_id == assignment.calendar_id,
                Booking.start_at == assignment.start_at,
                Booking.status == "confirmed",
            )
        )
        zone = require_timezone(operator.time_zone)
        subject, plain, markup = staff_content(
            kind,
            staff_name=staff.name,
            role=assignment.role,
            calendar_name=calendar.name,
            start=assignment.start_at.astimezone(zone),
            end=assignment.end_at.astimezone(zone),
            location=location,
            guests=int(guests or 0),
            operator_name=operator.name,
        )
        self._deliver(contact_id, subject, plain, markup, settings)

    def send_staff_unassigned(self, payload: dict[str, Any]) -> None:
        """Tell staff they were taken off a slot.

        Built from the snapshot queued at removal: the assignment row is gone.
        """
        staff = self.db.scalar(
            select(Staff).where(
                Staff.id == uuid.UUID(payload["staff_id"]), Staff.operator_id == self.operator_id
            )
        )
        start = datetime.fromisoformat(payload["start_at"])
        end = datetime.fromisoformat(payload["end_at"])
        if staff is None or staff.deleted_at is not None or not staff.email:
            return
        if start <= datetime.now(UTC):
            return
        row = self.db.execute(
            select(Operator, OperatorSettings)
            .outerjoin(OperatorSettings, OperatorSettings.operator_id == Operator.id)
            .where(Operator.id == self.operator_id)
        ).one_or_none()
        if row is None:
            return
        operator, settings = row
        contact_id = staff.ghl_contact_id or GHLContactService(self.db, self.operator_id).sync_staff(
            staff.id
        )
        if not contact_id:
            return
        location = (
            DepartureLocation(name=payload["location_name"], address=payload.get("location_address") or "")
            if payload.get("location_name")
            else None
        )
        zone = require_timezone(operator.time_zone)
        subject, plain, markup = staff_content(
            "unassigned",
            staff_name=staff.name,
            role=payload.get("role"),
            calendar_name=payload["calendar_name"],
            start=start.astimezone(zone),
            end=end.astimezone(zone),
            location=location,
            guests=None,
            operator_name=operator.name,
        )
        self._deliver(contact_id, subject, plain, markup, settings)

    @staticmethod
    def _content(
        order: BookingOrder,
        operator: Operator,
        bookings: list[Booking],
        waiver_links: dict[uuid.UUID, str] | None = None,
    ) -> tuple[str, str]:
        zone = require_timezone(operator.time_zone)
        waiver_links = waiver_links or {}
        text_parts = [
            f"Hi {order.customer_first_name},",
            "",
            "Your booking is confirmed.",
            f"Order: {order.public_reference}",
            "",
        ]
        html_parts = [
            f"<p>Hi {html.escape(order.customer_first_name)},</p>",
            "<p>Your booking is confirmed.</p>",
            f"<p><strong>Order:</strong> {html.escape(order.public_reference)}</p>",
        ]
        for booking in bookings:
            start = booking.start_at.astimezone(zone)
            end = booking.end_at.astimezone(zone)
            detail = [
                booking.calendar_name_snapshot,
                f"Date: {start:%B %d, %Y}",
                # Times are already converted to the operator zone above; label it
                # so the customer knows which timezone the booking is in.
                f"Time: {start.strftime('%I:%M %p').lstrip('0')} - "
                f"{end.strftime('%I:%M %p').lstrip('0')} {start.strftime('%Z')}",
                f"Quantity: {booking.units}",
            ]
            if booking.departure_location_name_snapshot:
                detail.append(f"Location: {booking.departure_location_name_snapshot}")
            if booking.departure_location_address_snapshot:
                detail.append(f"Address: {booking.departure_location_address_snapshot}")
            link = waiver_links.get(booking.id)
            text_parts.extend(detail)
            if link:
                text_parts.append(f"{WAIVER_LINK_LABEL}: {link}")
            text_parts.append("")
            html_parts.append(
                "<section><h3>"
                + html.escape(booking.calendar_name_snapshot)
                + "</h3><p>"
                + "<br>".join(html.escape(line) for line in detail[1:])
                + "</p>"
                + (_link_html(WAIVER_LINK_LABEL, link) if link else "")
                + "</section>"
            )
        totals = [
            f"Subtotal: {_money(order.subtotal_minor, order.currency)}",
            f"Platform Fee & Taxes: {_money(order.platform_fee_and_taxes_minor, order.currency)}",
            f"Total Paid: {_money(order.customer_total_minor, order.currency)}",
        ]
        text_parts.extend(["Payment:", *totals, "", "Thank you,", operator.name])
        html_parts.extend(
            [
                "<h3>Payment</h3><p>" + "<br>".join(html.escape(line) for line in totals) + "</p>",
                f"<p>Thank you,<br>{html.escape(operator.name)}</p>",
            ]
        )
        return "\n".join(text_parts), "".join(html_parts)
