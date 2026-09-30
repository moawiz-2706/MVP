from __future__ import annotations

from dataclasses import dataclass
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Booking, CalendarBookingPolicy


@dataclass(frozen=True, slots=True)
class PolicySnapshot:
    """The policy captured by a booking mutation, with safe defaults."""

    version: int
    cancellation_cutoff_minutes: int = 0
    cancellation_fee_bps: int = 0
    weather_refund_mode: str = "full_refund"
    reschedule_cutoff_minutes: int = 0
    reschedule_fee_minor: int = 0
    no_show_mode: str = "forfeit"
    deposit_bps: int = 0
    requires_waiver: bool = False


class PolicyService:
    """Resolve the immutable policy version attached to a booking."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def resolve_for_booking(self, booking: Booking) -> PolicySnapshot:
        policy = None
        if booking.booking_policy_version is not None:
            policy = self.db.scalar(
                select(CalendarBookingPolicy).where(
                    CalendarBookingPolicy.operator_id == booking.operator_id,
                    CalendarBookingPolicy.calendar_id == booking.calendar_id,
                    CalendarBookingPolicy.version == booking.booking_policy_version,
                )
            )
        if policy is None:
            policy = self.db.scalar(
                select(CalendarBookingPolicy)
                .where(
                    CalendarBookingPolicy.operator_id == booking.operator_id,
                    CalendarBookingPolicy.calendar_id == booking.calendar_id,
                    CalendarBookingPolicy.active.is_(True),
                )
                .order_by(CalendarBookingPolicy.version.desc())
            )
        if policy is None:
            return PolicySnapshot(version=booking.booking_policy_version or 0)
        return PolicySnapshot(
            version=policy.version,
            cancellation_cutoff_minutes=policy.cancellation_cutoff_minutes,
            cancellation_fee_bps=policy.cancellation_fee_bps,
            weather_refund_mode=policy.weather_refund_mode,
            reschedule_cutoff_minutes=policy.reschedule_cutoff_minutes,
            reschedule_fee_minor=policy.reschedule_fee_minor,
            no_show_mode=policy.no_show_mode,
            deposit_bps=policy.deposit_bps,
            requires_waiver=policy.requires_waiver,
        )

    def resolve_for_calendar(
        self, operator_id: uuid.UUID, calendar_id: uuid.UUID
    ) -> PolicySnapshot:
        row = self.db.scalar(
            select(CalendarBookingPolicy)
            .where(
                CalendarBookingPolicy.operator_id == operator_id,
                CalendarBookingPolicy.calendar_id == calendar_id,
                CalendarBookingPolicy.active.is_(True),
            )
            .order_by(CalendarBookingPolicy.version.desc())
        )
        if row is None:
            return PolicySnapshot(version=0)
        return PolicySnapshot(
            version=row.version,
            cancellation_cutoff_minutes=row.cancellation_cutoff_minutes,
            cancellation_fee_bps=row.cancellation_fee_bps,
            weather_refund_mode=row.weather_refund_mode,
            reschedule_cutoff_minutes=row.reschedule_cutoff_minutes,
            reschedule_fee_minor=row.reschedule_fee_minor,
            no_show_mode=row.no_show_mode,
            deposit_bps=row.deposit_bps,
            requires_waiver=row.requires_waiver,
        )
