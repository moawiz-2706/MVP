from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CapacityInterval:
    start_at: datetime
    end_at: datetime
    quantity: int

    def __post_init__(self) -> None:
        if self.start_at >= self.end_at:
            raise ValueError("Capacity interval start must be before end")
        if self.quantity <= 0:
            raise ValueError("Capacity quantity must be positive")


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and a_end > b_start


def reserved_for_interval(
    reservations: list[CapacityInterval], start_at: datetime, end_at: datetime
) -> int:
    # Capacity is constrained by the peak concurrent quantity, not by summing
    # every booking that touches a long requested interval.
    clipped = [
        CapacityInterval(
            max(reservation.start_at, start_at),
            min(reservation.end_at, end_at),
            reservation.quantity,
        )
        for reservation in reservations
        if overlaps(reservation.start_at, reservation.end_at, start_at, end_at)
    ]
    return peak_usage(clipped)


def peak_usage(reservations: list[CapacityInterval]) -> int:
    events: list[tuple[datetime, int, int]] = []
    for reservation in reservations:
        events.append((reservation.start_at, 1, reservation.quantity))
        events.append((reservation.end_at, 0, -reservation.quantity))
    current = peak = 0
    # End events sort first at a boundary, matching the strict overlap rule.
    for _, _, delta in sorted(events, key=lambda event: (event[0], event[1])):
        current += delta
        peak = max(peak, current)
    return peak


def batch_fits(
    capacity: int,
    existing: list[CapacityInterval],
    requested: list[CapacityInterval],
) -> bool:
    if capacity < 0:
        raise ValueError("Capacity cannot be negative")
    return peak_usage([*existing, *requested]) <= capacity
