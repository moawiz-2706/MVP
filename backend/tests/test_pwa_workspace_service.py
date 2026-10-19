from datetime import UTC, date

import pytest

from app.services.pwa_workspace_service import SEARCH_TYPES, local_day_bounds, parse_search_types


def test_parse_search_types_uses_all_types_when_omitted() -> None:
    assert parse_search_types(None) == set(SEARCH_TYPES)


def test_parse_search_types_accepts_trimmed_case_insensitive_values() -> None:
    assert parse_search_types(" booking, CUSTOMER ,waiver ") == {"booking", "customer", "waiver"}


def test_parse_search_types_rejects_unknown_type_without_broadening_search() -> None:
    with pytest.raises(ValueError, match="Unsupported search type: leads"):
        parse_search_types("booking,leads")


def test_local_day_bounds_observes_dst_short_day() -> None:
    start, end = local_day_bounds(date(2027, 3, 14), "America/New_York")
    assert start == start.astimezone(UTC)
    assert end == end.astimezone(UTC)
    assert (end - start).total_seconds() == 23 * 60 * 60


def test_local_day_bounds_uses_utc_for_invalid_timezone() -> None:
    start, end = local_day_bounds(date(2027, 2, 5), "Not/A_Timezone")
    assert start.isoformat() == "2027-02-05T00:00:00+00:00"
    assert (end - start).total_seconds() == 24 * 60 * 60
