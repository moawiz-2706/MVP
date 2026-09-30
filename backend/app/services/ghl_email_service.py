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
from app.services.message_template_service import MessageTemplateService, default_render
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
    if waiver_url:
        lines.append(f"{WAIVER_LINK_LABEL}: {waiver_url}")
    event_type = f"booking_reminder_{kind}"
    rendered = default_render(
        event_type,
        {
            "operator_name": operator.name,
            "customer_first_name": order.customer_first_name,
            "public_reference": order.public_reference,
            "calendar_name": booking.calendar_name_snapshot,
            "booking_details": "\n".join(lines),
            "start_date": booking.start_at.astimezone(zone).strftime("%B %d, %Y"),
            "start_time": _clock(booking.start_at.astimezone(zone)),
            "end_time": _clock(booking.end_at.astimezone(zone)),
            "time_zone": booking.start_at.astimezone(zone).strftime("%Z"),
            "location_name": booking.departure_location_name_snapshot or "",
            "location_address": booking.departure_location_address_snapshot or "",
            "units": booking.units,
            "waiver_url": waiver_url or "",
        },
    )
    return rendered.subject, rendered.body, rendered.html


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
    event_type = {
        "assigned": "staff_assignment",
        "unassigned": "staff_unassignment",
        "day_before": "staff_reminder_day_before",
        "same_day": "staff_reminder_same_day",
    }[kind]
    rendered = default_render(
        event_type,
        {
            "operator_name": operator_name,
            "staff_name": staff_name.split()[0] if staff_name.split() else staff_name,
            "staff_role": f" as {role}" if role else "",
            "calendar_name": calendar_name,
            "start_date": start.strftime("%b %d"),
            "start_time": _clock(start),
            "end_time": _clock(end),
            "booking_details": "\n".join(lines),
            "guests_booked": guests if guests is not None else "",
            "when": WHEN[kind] if kind in WHEN else "",
            "location_name": location.name if location else "",
            "location_address": location.address if location else "",
        },
    )
    return rendered.subject, rendered.body, rendered.html


class GHLEmailService:
    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id
        self.client = GHLClient(operator_id, db)

    @staticmethod
    def _booking_detail_lines(
        booking: Booking,
        operator: Operator,
        *,
        waiver_url: str | None = None,
        include_order: str | None = None,
    ) -> list[str]:
        zone = require_timezone(operator.time_zone)
        start = booking.start_at.astimezone(zone)
        end = booking.end_at.astimezone(zone)
        lines = [
            booking.calendar_name_snapshot,
            f"Date: {start:%B %d, %Y}",
            f"Time: {_clock(start)} - {_clock(end)} {start.strftime('%Z')}",
            f"Quantity: {booking.units}",
        ]
        if booking.departure_location_name_snapshot:
            lines.append(f"Location: {booking.departure_location_name_snapshot}")
        if booking.departure_location_address_snapshot:
            lines.append(f"Address: {booking.departure_location_address_snapshot}")
        if include_order:
            lines.append(f"Order: {include_order}")
        if waiver_url:
            lines.append(f"{WAIVER_LINK_LABEL}: {waiver_url}")
        return lines

    @classmethod
    def _order_context(
        cls,
        order: BookingOrder,
        operator: Operator,
        bookings: list[Booking],
        waiver_links: dict[uuid.UUID, str] | None = None,
    ) -> dict[str, Any]:
        waiver_links = waiver_links or {}
        zone = require_timezone(operator.time_zone)
        detail_blocks = [
            "\n".join(
                cls._booking_detail_lines(
                    booking,
                    operator,
                    waiver_url=waiver_links.get(booking.id),
                )
            )
            for booking in bookings
        ]
        first = bookings[0] if bookings else None
        start = first.start_at.astimezone(zone) if first else None
        end = first.end_at.astimezone(zone) if first else None
        return {
            "operator_name": operator.name,
            "operator_slug": operator.slug,
            "customer_first_name": order.customer_first_name,
            "customer_last_name": order.customer_last_name,
            "customer_email": order.customer_email,
            "public_reference": order.public_reference,
            "calendar_name": first.calendar_name_snapshot if first else "Your booking",
            "booking_details": "\n\n".join(detail_blocks),
            "payment_summary": "\n".join(
                [
                    f"Subtotal: {_money(order.subtotal_minor, order.currency)}",
                    f"Platform Fee & Taxes: {_money(order.platform_fee_and_taxes_minor, order.currency)}",
                    f"Total Paid: {_money(order.customer_total_minor, order.currency)}",
                ]
            ),
            "start_date": start.strftime("%B %d, %Y") if start else "",
            "start_time": _clock(start) if start else "",
            "end_time": _clock(end) if end else "",
            "time_zone": start.strftime("%Z") if start else operator.time_zone,
            "location_name": first.departure_location_name_snapshot if first else "",
            "location_address": first.departure_location_address_snapshot if first else "",
            "units": first.units if first else "",
            "currency": order.currency.upper(),
            "booking_total": _money(order.customer_total_minor, order.currency),
        }

    @classmethod
    def _booking_context(
        cls,
        order: BookingOrder,
        operator: Operator,
        booking: Booking,
        *,
        waiver_url: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        context = cls._order_context(order, operator, [booking], {booking.id: waiver_url} if waiver_url else {})
        context["waiver_url"] = waiver_url or ""
        context.update(extra)
        return context

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
        template_service = MessageTemplateService(self.db, self.operator_id)
        rendered = template_service.render(
            "booking_confirmation", self._order_context(order, operator, bookings, waiver_links)
        )
        if not rendered.enabled:
            order.ghl_confirmation_email_status = "disabled"
            self.db.commit()
            return
        _definition, _enabled, is_custom = template_service.definition("booking_confirmation")
        subject = rendered.subject
        if not is_custom and settings and settings.confirmation_email_subject != "Booking Confirmation":
            subject = f"{settings.confirmation_email_subject} - {operator.name}"
        response = self._deliver(
            order.ghl_contact_id,
            subject,
            rendered.body,
            rendered.html,
            settings,
        )
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
        rendered = MessageTemplateService(self.db, self.operator_id).render(
            f"booking_reminder_{kind}",
            self._booking_context(order, operator, booking, waiver_url=waiver_link, when=WHEN[kind]),
        )
        if rendered.enabled:
            self._deliver(contact_id, rendered.subject, rendered.body, rendered.html, settings)

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
        start = assignment.start_at.astimezone(zone)
        end = assignment.end_at.astimezone(zone)
        detail_lines = _when_lines(start, end)
        if assignment.role:
            detail_lines.append(f"Role: {assignment.role}")
        if location:
            detail_lines.extend([f"Location: {location.name}", f"Address: {location.address}"])
        event_type = "staff_assignment" if kind == "assigned" else f"staff_reminder_{kind}"
        rendered = MessageTemplateService(self.db, self.operator_id).render(
            event_type,
            {
                "operator_name": operator.name,
                "staff_name": staff.name.split()[0] if staff.name.split() else staff.name,
                "staff_role": f" as {assignment.role}" if assignment.role else "",
                "calendar_name": calendar.name,
                "start_date": start.strftime("%b %d"),
                "start_time": _clock(start),
                "end_time": _clock(end),
                "time_zone": start.strftime("%Z"),
                "booking_details": "\n".join(detail_lines),
                "guests_booked": int(guests or 0),
                "when": WHEN.get(kind, ""),
                "location_name": location.name if location else "",
                "location_address": location.address if location else "",
            },
        )
        if rendered.enabled:
            self._deliver(contact_id, rendered.subject, rendered.body, rendered.html, settings)

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
        local_start = start.astimezone(zone)
        local_end = end.astimezone(zone)
        detail_lines = _when_lines(local_start, local_end)
        if payload.get("role"):
            detail_lines.append(f"Role: {payload['role']}")
        if location:
            detail_lines.extend([f"Location: {location.name}", f"Address: {location.address}"])
        rendered = MessageTemplateService(self.db, self.operator_id).render(
            "staff_unassignment",
            {
                "operator_name": operator.name,
                "staff_name": staff.name.split()[0] if staff.name.split() else staff.name,
                "staff_role": f" as {payload.get('role')}" if payload.get("role") else "",
                "calendar_name": payload["calendar_name"],
                "start_date": local_start.strftime("%b %d"),
                "start_time": _clock(local_start),
                "end_time": _clock(local_end),
                "time_zone": local_start.strftime("%Z"),
                "booking_details": "\n".join(detail_lines),
                "guests_booked": "",
                "location_name": location.name if location else "",
                "location_address": location.address if location else "",
            },
        )
        if rendered.enabled:
            self._deliver(contact_id, rendered.subject, rendered.body, rendered.html, settings)

    def _send_booking_event(
        self,
        booking_id: uuid.UUID,
        event_type: str,
        *,
        reason: str = "",
        adjustment_outcome: str = "",
        previous_start: str = "",
        payment_outcome: str = "",
    ) -> None:
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
        if settings and not settings.confirmation_email_enabled:
            return
        contact_id = order.ghl_contact_id or GHLContactService(self.db, self.operator_id).sync(order.id)
        if not contact_id:
            return
        context = self._booking_context(
            order,
            operator,
            booking,
            cancel_reason=reason,
            adjustment_outcome=adjustment_outcome,
            previous_start=previous_start,
            payment_outcome=payment_outcome,
        )
        rendered = MessageTemplateService(self.db, self.operator_id).render(event_type, context)
        if rendered.enabled:
            self._deliver(contact_id, rendered.subject, rendered.body, rendered.html, settings)

    def send_booking_cancellation(
        self, booking_id: uuid.UUID, *, reason: str, adjustment_outcome: str = ""
    ) -> None:
        self._send_booking_event(
            booking_id,
            "booking_cancellation",
            reason=reason,
            adjustment_outcome=adjustment_outcome,
        )

    def send_booking_weather_cancellation(
        self, booking_id: uuid.UUID, *, reason: str, adjustment_outcome: str = ""
    ) -> None:
        self._send_booking_event(
            booking_id,
            "weather_cancellation",
            reason=reason,
            adjustment_outcome=adjustment_outcome,
        )

    def send_booking_reschedule(
        self,
        booking_id: uuid.UUID,
        *,
        reason: str,
        previous_start: str,
        payment_outcome: str = "",
    ) -> None:
        self._send_booking_event(
            booking_id,
            "booking_reschedule",
            reason=reason,
            previous_start=previous_start,
            payment_outcome=payment_outcome,
        )

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
