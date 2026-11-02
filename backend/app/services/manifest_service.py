from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import (
    Booking,
    BookingEvent,
    BookingOrder,
    BookingParticipant,
    BookingWaiver,
    Calendar,
    Payment,
)
from app.schemas.pwa import PWAManifestBooking, PWAManifestParticipant, PWAManifestResponse
from app.services.departure_board_service import INACTIVE_BOOKING_STATUSES, DepartureBoardService

CHECK_IN_BLOCKED = INACTIVE_BOOKING_STATUSES | {"no_show"}


def _participant(item: BookingParticipant) -> PWAManifestParticipant:
    return PWAManifestParticipant(
        id=item.id,
        sequence=item.sequence,
        name=f"{item.first_name} {item.last_name}".strip(),
        is_minor=item.is_minor,
        guardian_name=item.guardian_name,
        phone=item.phone,
        email=item.email,
        checked_in_at=item.checked_in_at,
    )


class ManifestService:
    """Passenger manifest for one departure, and per-person check-in."""

    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id

    def manifest(self, calendar_id: uuid.UUID, start_at: datetime) -> PWAManifestResponse:
        calendar = self.db.scalar(
            select(Calendar).where(Calendar.id == calendar_id, Calendar.operator_id == self.operator_id)
        )
        if calendar is None:
            raise NotFoundError("Calendar not found")
        start_at = start_at.astimezone(UTC)
        rows = self.db.execute(
            select(Booking, BookingOrder, Payment)
            .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
            .outerjoin(Payment, Payment.booking_order_id == BookingOrder.id)
            .where(
                Booking.operator_id == self.operator_id,
                Booking.calendar_id == calendar.id,
                Booking.start_at == start_at,
                Booking.status.not_in(tuple(INACTIVE_BOOKING_STATUSES)),
            )
            .order_by(BookingOrder.customer_last_name, BookingOrder.customer_first_name, Booking.id)
        ).all()
        booking_ids = [booking.id for booking, _order, _payment in rows]
        participants: dict[uuid.UUID, list[BookingParticipant]] = {booking_id: [] for booking_id in booking_ids}
        waivers: dict[uuid.UUID, list[str]] = {booking_id: [] for booking_id in booking_ids}
        if booking_ids:
            for participant in self.db.scalars(
                select(BookingParticipant)
                .where(BookingParticipant.booking_id.in_(booking_ids), BookingParticipant.status != "cancelled")
                .order_by(BookingParticipant.sequence)
            ):
                participants[participant.booking_id].append(participant)
            for booking_id, status in self.db.execute(
                select(BookingWaiver.booking_id, BookingWaiver.status).where(BookingWaiver.booking_id.in_(booking_ids))
            ):
                waivers[booking_id].append(status)

        bookings = []
        end_at = start_at + timedelta(minutes=calendar.duration_minutes)
        for booking, order, payment in rows:
            end_at = max(end_at, booking.end_at.astimezone(UTC))
            statuses = waivers[booking.id]
            bookings.append(
                PWAManifestBooking(
                    id=booking.id,
                    public_reference=order.public_reference,
                    lead_name=f"{order.customer_first_name} {order.customer_last_name}".strip(),
                    lead_phone=order.customer_phone,
                    lead_email=order.customer_email,
                    status=booking.status,
                    payment_status=payment.status if payment else None,
                    payment_method=payment.payment_method if payment else None,
                    units=booking.units,
                    waiver_status=(
                        "none" if not statuses else "signed" if all(s == "signed" for s in statuses) else "pending"
                    ),
                    participants=[_participant(item) for item in participants[booking.id]],
                )
            )
        board_service = DepartureBoardService(self.db, self.operator_id)
        board = board_service.day(board_service.local_date(start_at), calendar_id=calendar.id)
        departure = next((item for item in board.departures if item.start_at == start_at), None)
        named = [p for booking in bookings for p in booking.participants]
        return PWAManifestResponse(
            calendar_id=calendar.id,
            calendar_name=calendar.name,
            start_at=start_at,
            end_at=end_at,
            time_zone=board.time_zone,
            expected_units=sum(booking.units for booking in bookings),
            named_participants=len(named),
            checked_in=sum(1 for p in named if p.checked_in_at is not None),
            staff=departure.staff if departure else [],
            bookings=bookings,
        )

    def set_check_in(self, participant_id: uuid.UUID, checked_in: bool, actor_id: uuid.UUID) -> PWAManifestParticipant:
        participant = self.db.scalar(
            select(BookingParticipant)
            .where(BookingParticipant.id == participant_id, BookingParticipant.operator_id == self.operator_id)
            .with_for_update()
        )
        if participant is None or participant.status == "cancelled":
            raise NotFoundError("Participant not found")
        booking = self.db.get(Booking, participant.booking_id)
        if booking is None or booking.operator_id != self.operator_id:
            raise NotFoundError("Booking not found")
        if checked_in and booking.status in CHECK_IN_BLOCKED:
            raise ConflictError(f"Cannot check in a guest on a {booking.status.replace('_', ' ')} booking")
        if (participant.checked_in_at is None) == checked_in:
            # Only a real change is recorded: a double tap or retried request keeps
            # the first timestamp and writes no second audit event.
            now = datetime.now(UTC)
            participant.checked_in_at = now if checked_in else None
            participant.checked_in_by_user_id = actor_id if checked_in else None
            self.db.add(
                BookingEvent(
                    operator_id=self.operator_id,
                    booking_id=booking.id,
                    order_id=booking.booking_order_id,
                    event_type="participant_checked_in" if checked_in else "participant_check_in_undone",
                    actor_type="operator",
                    actor_id=actor_id,
                    payload={"participant_id": str(participant.id), "sequence": participant.sequence},
                    occurred_at=now,
                )
            )
        self.db.commit()
        return _participant(participant)
