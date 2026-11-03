"""One description of an order for HighLevel, shared by the contact fields and
the Passport Booking record so both always say the same thing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Booking,
    BookingOrder,
    BookingParticipant,
    BookingWaiver,
    Operator,
    Payment,
    Staff,
    StaffAssignment,
)

INACTIVE = {"cancelled", "failed", "expired"}


def _amount(minor: int | None) -> str:
    return f"{Decimal(int(minor or 0)) / Decimal(100):.2f}"


def _local(value: datetime | None, zone: ZoneInfo) -> str:
    if value is None:
        return ""
    local = value.astimezone(zone)
    return f"{local:%A, %B} {local.day}, {local.year} at {local.hour % 12 or 12}:{local:%M %p}"


@dataclass(frozen=True)
class BookingFacts:
    booking_reference: str
    booking_id: str
    booking_status: str
    payment_status: str
    payment_method: str
    invoice_status: str
    customer_name: str
    customer_email: str
    customer_phone: str
    activity: str
    tour_start: str
    tour_start_utc: str
    tour_end_utc: str
    guests: int
    total_amount: str
    currency: str
    source_partner: str
    assigned_staff: str
    waiver_status: str
    waiver_link: str
    waiver_signed_at: str
    waiver_expires_at: str
    emergency_contact: str
    marketing_opt_in: bool
    lead_date_of_birth: date | None


def booking_facts(db: Session, order: BookingOrder) -> BookingFacts:
    from app.services.waiver_service import WaiverService

    operator = db.get(Operator, order.operator_id)
    try:
        zone = ZoneInfo(operator.time_zone) if operator and operator.time_zone else ZoneInfo("UTC")
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    payment = db.scalar(select(Payment).where(Payment.booking_order_id == order.id))
    bookings = list(
        db.scalars(
            select(Booking)
            .where(Booking.booking_order_id == order.id, Booking.operator_id == order.operator_id)
            .order_by(Booking.start_at, Booking.id)
        )
    )
    active = [booking for booking in bookings if booking.status not in INACTIVE] or bookings
    waivers = WaiverService(db)
    summaries = [waivers.summary(booking) for booking in bookings]
    statuses = list(dict.fromkeys(str(item.get("status") or "") for item in summaries))
    links = [str(item["url"]) for item in summaries if item.get("url")]
    signed = [item["signed_at"] for item in summaries if item.get("signed_at")]
    expiries = [
        waiver.public_expires_at
        for waiver in db.scalars(
            select(BookingWaiver).where(BookingWaiver.booking_id.in_([b.id for b in bookings]))
        )
        if waiver.public_expires_at
    ] if bookings else []
    participants = list(
        db.scalars(
            select(BookingParticipant)
            .where(BookingParticipant.booking_id.in_([b.id for b in bookings]))
            .order_by(BookingParticipant.sequence)
        )
    ) if bookings else []
    # The lead booker is the participant with the order's email, else the first adult.
    email = (order.customer_email or "").casefold()
    lead = next(
        (p for p in participants if (p.email or "").casefold() == email and not p.is_minor),
        next((p for p in participants if not p.is_minor), None),
    )
    emergency = ""
    if lead is not None and isinstance(lead.emergency_contact, dict):
        emergency = ", ".join(
            str(value).strip() for value in lead.emergency_contact.values() if str(value or "").strip()
        )
    staff = []
    for booking in active:
        staff.extend(
            db.scalars(
                select(Staff.name)
                .join(StaffAssignment, StaffAssignment.staff_id == Staff.id)
                .where(
                    StaffAssignment.operator_id == order.operator_id,
                    StaffAssignment.calendar_id == booking.calendar_id,
                    StaffAssignment.start_at == booking.start_at,
                )
            )
        )
    first = active[0] if active else None
    return BookingFacts(
        booking_reference=order.public_reference,
        booking_id=str(order.id),
        booking_status=order.status,
        payment_status=payment.status if payment else "",
        payment_method=payment.payment_method if payment else "",
        invoice_status=(payment.invoice_status or "") if payment else "",
        customer_name=f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip(),
        customer_email=order.customer_email or "",
        customer_phone=order.customer_phone or "",
        activity=", ".join(dict.fromkeys(b.calendar_name_snapshot for b in active)),
        tour_start=_local(first.start_at, zone) if first else "",
        tour_start_utc=first.start_at.isoformat() if first else "",
        tour_end_utc=max(b.end_at for b in active).isoformat() if active else "",
        guests=sum(b.units for b in active),
        total_amount=_amount(order.customer_total_minor),
        currency=(order.currency or "").upper(),
        source_partner=order.partner_name_snapshot or "Direct",
        assigned_staff=", ".join(dict.fromkeys(staff)),
        waiver_status=", ".join(status for status in statuses if status),
        waiver_link="\n".join(links),
        waiver_signed_at=max(signed).isoformat() if signed else "",
        waiver_expires_at=min(expiries).isoformat() if expiries else "",
        emergency_contact=emergency,
        marketing_opt_in=bool(order.marketing_opt_in),
        lead_date_of_birth=lead.date_of_birth if lead else None,
    )


def object_properties(facts: BookingFacts) -> dict[str, str]:
    """Passport Booking record values by field key (create the fields in HighLevel)."""
    return {
        "booking_reference": facts.booking_reference,
        "passport_booking_id": facts.booking_id,
        "booking_status": facts.booking_status,
        "payment_status": facts.payment_status,
        "payment_method": facts.payment_method,
        "invoice_status": facts.invoice_status,
        "customer_name": facts.customer_name,
        "customer_email": facts.customer_email,
        "customer_phone": facts.customer_phone,
        "activity": facts.activity,
        "tour_start": facts.tour_start,
        "guests": str(facts.guests),
        "total_amount": facts.total_amount,
        "source_partner": facts.source_partner,
        "assigned_staff": facts.assigned_staff,
        "waiver_status": facts.waiver_status,
        "waiver_link": facts.waiver_link,
        "waiver_signed_at": facts.waiver_signed_at,
        "emergency_contact": facts.emergency_contact,
    }


# The five fields the object had on 3 Nov 2026; sent when its field list
# cannot be read.
BASE_OBJECT_FIELDS = {"booking_reference", "passport_booking_id", "payment_status", "invoice_status", "waiver_status"}


def contact_values(facts: BookingFacts) -> dict[str, str]:
    """Contact custom field values by Passport key (fields named "Passport …")."""
    return {
        "passport_booking_id": facts.booking_id,
        "passport_booking_reference": facts.booking_reference,
        "passport_booking_status": facts.booking_status,
        "passport_payment_status": facts.payment_status,
        "passport_service_name": facts.activity,
        "passport_quantity": str(facts.guests),
        "passport_total": facts.total_amount,
        "passport_currency": facts.currency,
        "passport_start_at": facts.tour_start_utc,
        "passport_end_at": facts.tour_end_utc,
        "passport_tour_start": facts.tour_start,
        "passport_source_partner": facts.source_partner,
        "passport_waiver_url": facts.waiver_link,
        "passport_waiver_status": facts.waiver_status,
        "passport_waiver_signed_at": facts.waiver_signed_at,
        "passport_waiver_expires_at": facts.waiver_expires_at,
        "passport_emergency_contact": facts.emergency_contact,
        "passport_marketing_opt_in": str(facts.marketing_opt_in).lower(),
    }
