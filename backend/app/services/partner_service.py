"""Hotel partners and the revenue split on the bookings they send.

Split rules (agreed scope):

* gross_booking_amount = the booking price before tax, booking fee and
  gratuity (the order subtotal), reduced in proportion to any refund.
* A cancelled, refunded or expired order has a zero split.
* Partner booking: hotel = gross x hotel rate (20%), PGA = gross x PGA rate
  (30%), operator = gross - hotel - PGA (50%), so the parts always add up.
* Direct booking (no partner): operator keeps 100%.
* Gratuity is not collected yet and is always 0.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import BookingOrder, BookingPartner, Payment
from app.utils.money import apply_basis_points

DIRECT = "Direct"
DEFAULT_HOTEL_BPS = 2000
DEFAULT_PGA_BPS = 3000
ZERO_SPLIT_STATUSES = {"cancelled", "refunded", "expired"}
_CODE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class PartnerSplit:
    source_partner: str
    gross_minor: int
    hotel_commission_minor: int
    pga_commission_minor: int
    net_to_operator_minor: int
    gratuity_minor: int = 0


def partner_split(order: BookingOrder, payment: Payment | None) -> PartnerSplit:
    source = order.partner_name_snapshot or DIRECT
    if order.status in ZERO_SPLIT_STATUSES:
        return PartnerSplit(source, 0, 0, 0, 0)
    gross = max(0, int(order.subtotal_minor or 0))
    total = int(order.customer_total_minor or 0)
    refunded = int(payment.refunded_minor or 0) if payment else 0
    if refunded and total > 0:
        # A partial refund reduces the price, tax and fee alike, so the gross
        # keeps the share of the subtotal that was not given back.
        gross = (gross * max(0, total - refunded)) // total
    if order.partner_id is None:
        return PartnerSplit(source, gross, 0, 0, gross)
    hotel = apply_basis_points(gross, order.partner_hotel_bps or 0)
    pga = apply_basis_points(gross, order.partner_pga_bps or 0)
    return PartnerSplit(source, gross, hotel, pga, gross - hotel - pga)


def partner_code(value: str) -> str:
    return _CODE.sub("-", value.strip().lower()).strip("-")


class PartnerService:
    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id

    def list(self, *, include_inactive: bool = True) -> list[BookingPartner]:
        conditions = [BookingPartner.operator_id == self.operator_id, BookingPartner.deleted_at.is_(None)]
        if not include_inactive:
            conditions.append(BookingPartner.is_active.is_(True))
        return list(self.db.scalars(select(BookingPartner).where(*conditions).order_by(BookingPartner.name)))

    def get(self, partner_id: uuid.UUID) -> BookingPartner:
        partner = self.db.scalar(
            select(BookingPartner).where(
                BookingPartner.id == partner_id,
                BookingPartner.operator_id == self.operator_id,
                BookingPartner.deleted_at.is_(None),
            )
        )
        if partner is None:
            raise NotFoundError("Partner not found")
        return partner

    def active_by_code(self, code: str | None) -> BookingPartner | None:
        """The partner behind a booking link's `?partner=` code.

        An unknown or switched-off code books as Direct rather than failing:
        a stale QR code must never stop a customer from booking.
        """
        if not code:
            return None
        return self.db.scalar(
            select(BookingPartner).where(
                BookingPartner.operator_id == self.operator_id,
                BookingPartner.code == partner_code(code),
                BookingPartner.is_active.is_(True),
                BookingPartner.deleted_at.is_(None),
            )
        )

    def active_by_id(self, partner_id: uuid.UUID) -> BookingPartner:
        partner = self.get(partner_id)
        if not partner.is_active:
            raise ConflictError("This partner is switched off")
        return partner

    def create(self, values: dict[str, Any]) -> BookingPartner:
        partner = BookingPartner(
            operator_id=self.operator_id,
            name=values["name"].strip(),
            code=partner_code(values.get("code") or values["name"]),
            hotel_commission_bps=values.get("hotel_commission_bps", DEFAULT_HOTEL_BPS),
            pga_commission_bps=values.get("pga_commission_bps", DEFAULT_PGA_BPS),
            is_active=values.get("is_active", True),
        )
        self._validate(partner)
        self.db.add(partner)
        self._commit()
        self.db.refresh(partner)
        return partner

    def update(self, partner_id: uuid.UUID, values: dict[str, Any]) -> BookingPartner:
        partner = self.get(partner_id)
        for key in ("hotel_commission_bps", "pga_commission_bps", "is_active"):
            if key in values and values[key] is not None:
                setattr(partner, key, values[key])
        if values.get("name"):
            partner.name = values["name"].strip()
        if values.get("code"):
            partner.code = partner_code(values["code"])
        self._validate(partner)
        self._commit()
        self.db.refresh(partner)
        return partner

    def delete(self, partner_id: uuid.UUID) -> None:
        partner = self.get(partner_id)
        # Kept for the bookings it sent; only hidden and switched off.
        partner.deleted_at = datetime.now(UTC)
        partner.is_active = False
        self.db.commit()

    @staticmethod
    def _validate(partner: BookingPartner) -> None:
        if not partner.name or not partner.code:
            raise ConflictError("A partner needs a name")
        if partner.code == partner_code(DIRECT):
            raise ConflictError('"Direct" is the default for bookings without a partner')
        hotel, pga = partner.hotel_commission_bps, partner.pga_commission_bps
        if not (0 <= hotel <= 10_000 and 0 <= pga <= 10_000 and hotel + pga <= 10_000):
            raise ConflictError("Hotel and PGA commission together cannot exceed 100%")

    def _commit(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("A partner with that link code already exists") from exc


def tag_order(order: BookingOrder, partner: BookingPartner | None) -> None:
    """Record the partner and its current rates on a new order."""
    if partner is None:
        return
    order.partner_id = partner.id
    order.partner_name_snapshot = partner.name
    order.partner_hotel_bps = partner.hotel_commission_bps
    order.partner_pga_bps = partner.pga_commission_bps


REPORT_EXCLUDED_STATUSES = {"pending_payment", "expired", "exception"}
GUEST_EXCLUDED_BOOKING_STATUSES = {"failed", "expired"}


def commission_report(
    db: Session, operator_id: uuid.UUID, start_date: date, end_date: date, time_zone: str
) -> list[dict[str, Any]]:
    """Split per partner for orders whose first tour falls in the dates.

    Grouped by tour date (operator-local), the date a hotel is usually paid
    against. Unpaid holds and expired or problem orders are left out;
    cancelled and refunded orders count with their zero split.
    """
    from app.models.entities import Booking
    from app.services.pwa_workspace_service import local_day_bounds

    range_start, _ = local_day_bounds(start_date, time_zone)
    _, range_end = local_day_bounds(end_date, time_zone)
    first_tour = (
        select(Booking.booking_order_id, func.min(Booking.start_at).label("first_start"))
        .where(Booking.operator_id == operator_id)
        .group_by(Booking.booking_order_id)
        .subquery()
    )
    rows = db.execute(
        select(BookingOrder, Payment)
        .join(first_tour, first_tour.c.booking_order_id == BookingOrder.id)
        .outerjoin(Payment, Payment.booking_order_id == BookingOrder.id)
        .where(
            BookingOrder.operator_id == operator_id,
            BookingOrder.status.not_in(REPORT_EXCLUDED_STATUSES),
            first_tour.c.first_start >= range_start,
            first_tour.c.first_start < range_end,
        )
    ).all()
    guests = dict(
        db.execute(
            select(Booking.booking_order_id, func.coalesce(func.sum(Booking.units), 0))
            .where(
                Booking.booking_order_id.in_([order.id for order, _ in rows]),
                Booking.status.not_in(GUEST_EXCLUDED_BOOKING_STATUSES),
            )
            .group_by(Booking.booking_order_id)
        ).all()
    ) if rows else {}
    totals: dict[tuple, dict[str, Any]] = {}
    for order, payment in rows:
        split = partner_split(order, payment)
        key = (order.partner_id, split.source_partner, order.currency)
        row = totals.setdefault(
            key,
            {
                "source_partner": split.source_partner,
                "partner_id": order.partner_id,
                "bookings": 0,
                "guests": 0,
                "gross_minor": 0,
                "hotel_commission_minor": 0,
                "pga_commission_minor": 0,
                "net_to_operator_minor": 0,
                "currency": order.currency,
            },
        )
        if split.gross_minor:
            row["bookings"] += 1
            row["guests"] += int(guests.get(order.id, 0))
        row["gross_minor"] += split.gross_minor
        row["hotel_commission_minor"] += split.hotel_commission_minor
        row["pga_commission_minor"] += split.pga_commission_minor
        row["net_to_operator_minor"] += split.net_to_operator_minor
    # Partners first by commission, Direct last.
    return sorted(
        totals.values(),
        key=lambda row: (row["partner_id"] is None, -row["hotel_commission_minor"], row["source_partner"].lower()),
    )
