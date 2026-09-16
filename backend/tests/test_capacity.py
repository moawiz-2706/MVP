from datetime import UTC, datetime

from app.services.capacity import (
    CapacityInterval,
    batch_fits,
    overlaps,
    peak_usage,
    reserved_for_interval,
)


def at(hour: int) -> datetime:
    return datetime(2027, 1, 10, hour, tzinfo=UTC)


def test_touching_boundaries_do_not_overlap() -> None:
    assert not overlaps(at(8), at(11), at(11), at(13))
    assert overlaps(at(8), at(11), at(10), at(13))


def test_peak_not_sum_of_nonconcurrent_reservations() -> None:
    reservations = [
        CapacityInterval(at(8), at(9), 6),
        CapacityInterval(at(10), at(11), 7),
    ]
    assert reserved_for_interval(reservations, at(8), at(12)) == 7


def test_shared_overlapping_usage() -> None:
    reservations = [
        CapacityInterval(at(9), at(11), 4),
        CapacityInterval(at(8), at(12), 5),
    ]
    assert reserved_for_interval(reservations, at(10), at(13)) == 9
    assert batch_fits(15, reservations, [CapacityInterval(at(10), at(13), 6)])
    assert not batch_fits(15, reservations, [CapacityInterval(at(10), at(13), 7)])


def test_batch_detects_items_that_overbook_each_other() -> None:
    requested = [
        CapacityInterval(at(8), at(11), 8),
        CapacityInterval(at(9), at(12), 8),
    ]
    assert not batch_fits(15, [], requested)


def test_non_overlapping_items_reuse_inventory() -> None:
    requested = [
        CapacityInterval(at(8), at(11), 15),
        CapacityInterval(at(11), at(14), 15),
    ]
    assert batch_fits(15, [], requested)
    assert peak_usage(requested) == 15


def test_exactly_one_unit_capacity() -> None:
    first = CapacityInterval(at(8), at(11), 1)
    second = CapacityInterval(at(9), at(10), 1)
    assert batch_fits(1, [], [first])
    assert not batch_fits(1, [first], [second])


def available(capacity: int, reservations: list[CapacityInterval], start, end) -> int:
    return capacity - reserved_for_interval(reservations, start, end)


# --- Spec §153: shared-resource availability math -------------------------


def test_spec153_1_no_bookings_full_capacity() -> None:
    # 15 resources, no bookings, request 4 => 15 available, sufficient.
    assert available(15, [], at(9), at(13)) == 15
    assert batch_fits(15, [], [CapacityInterval(at(9), at(13), 4)])


def test_spec153_2_existing_six_leaves_nine() -> None:
    # 15 resources, existing overlapping booking uses 6, request 4 => 9 available.
    existing = [CapacityInterval(at(9), at(11), 6)]
    assert available(15, existing, at(10), at(13)) == 9
    assert batch_fits(15, existing, [CapacityInterval(at(10), at(13), 4)])


def test_spec153_3_existing_twelve_rejects_four() -> None:
    # 15 resources, existing uses 12, request 4 => unavailable.
    existing = [CapacityInterval(at(9), at(13), 12)]
    assert available(15, existing, at(10), at(12)) == 3
    assert not batch_fits(15, existing, [CapacityInterval(at(10), at(12), 4)])


def test_spec153_4_touching_boundary_no_overlap() -> None:
    # existing 8-11, requested 11-1 => no overlap, full capacity remains.
    existing = [CapacityInterval(at(8), at(11), 15)]
    assert available(15, existing, at(11), at(13)) == 15


def test_spec153_5_and_6_overlap_detected() -> None:
    # existing 8-11 requested 10-1 => overlap; existing 8-17 requested 10-11 => overlap.
    assert overlaps(at(8), at(11), at(10), at(13))
    assert overlaps(at(8), at(17), at(10), at(11))


def test_spec153_13_shared_across_calendars_reduces_availability() -> None:
    # Two different calendars consume the same pool; availability is the union.
    kayaks_two_hour = CapacityInterval(at(9), at(11), 4)
    kayaks_four_hour = CapacityInterval(at(8), at(12), 5)
    assert available(15, [kayaks_two_hour, kayaks_four_hour], at(10), at(13)) == 6


# --- Spec §154: batch / concurrency capacity logic ------------------------


def test_spec154_18_single_unit_pool_serializes() -> None:
    # Resource quantity 1: once held for a window, an overlapping request cannot fit.
    held = CapacityInterval(at(8), at(11), 1)
    assert not batch_fits(1, [held], [CapacityInterval(at(9), at(10), 1)])


def test_spec154_19_two_requests_each_ten_of_fifteen() -> None:
    # Two overlapping requests each needing 10 of 15 cannot both hold.
    first = CapacityInterval(at(8), at(11), 10)
    second = CapacityInterval(at(9), at(12), 10)
    assert not batch_fits(15, [first], [second])
    assert not batch_fits(15, [], [first, second])


def test_spec154_20_order_items_overbook_each_other() -> None:
    # 8+8 over a 15 pool during their 9-11 overlap => whole order rejected.
    order = [CapacityInterval(at(8), at(11), 8), CapacityInterval(at(9), at(12), 8)]
    assert not batch_fits(15, [], order)


def test_spec154_21_non_overlapping_order_items_reuse_pool() -> None:
    order = [CapacityInterval(at(8), at(11), 15), CapacityInterval(at(11), at(14), 15)]
    assert batch_fits(15, [], order)

