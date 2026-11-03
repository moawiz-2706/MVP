"""Hotel partners: the 20/30/50 split and how bookings are tagged."""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import ConflictError
from app.services.partner_service import PartnerService, partner_code, partner_split, tag_order


def _order(*, status="confirmed", subtotal=10_000, total=11_300, partner=True, hotel=2000, pga=3000):
    return SimpleNamespace(
        status=status, subtotal_minor=subtotal, customer_total_minor=total,
        partner_id=uuid.uuid4() if partner else None,
        partner_name_snapshot="Sunseeker" if partner else None,
        partner_hotel_bps=hotel if partner else None, partner_pga_bps=pga if partner else None,
    )


def _payment(refunded=0):
    return SimpleNamespace(refunded_minor=refunded)


def test_partner_split_is_20_30_50_of_the_price_before_tax_and_fees():
    split = partner_split(_order(), _payment())
    assert (split.source_partner, split.gross_minor) == ("Sunseeker", 10_000)
    assert (split.hotel_commission_minor, split.pga_commission_minor, split.net_to_operator_minor) == (2_000, 3_000, 5_000)
    assert split.gratuity_minor == 0


def test_direct_keeps_100_percent():
    split = partner_split(_order(partner=False), _payment())
    assert (split.source_partner, split.hotel_commission_minor, split.pga_commission_minor, split.net_to_operator_minor) == (
        "Direct", 0, 0, 10_000
    )


@pytest.mark.parametrize("status", ["cancelled", "refunded", "expired"])
def test_cancelled_or_refunded_order_has_no_split(status):
    split = partner_split(_order(status=status), _payment(11_300))
    assert (split.gross_minor, split.hotel_commission_minor, split.pga_commission_minor, split.net_to_operator_minor) == (0, 0, 0, 0)


def test_partial_refund_recalculates_proportionally():
    # Half of the 113.00 charged was refunded: gross falls to 50.00.
    split = partner_split(_order(status="partially_refunded"), _payment(5_650))
    assert (split.gross_minor, split.hotel_commission_minor, split.pga_commission_minor, split.net_to_operator_minor) == (
        5_000, 1_000, 1_500, 2_500
    )


@pytest.mark.parametrize("subtotal", [1, 3, 999, 12_345, 33_333])
def test_parts_always_add_up_to_gross(subtotal):
    split = partner_split(_order(subtotal=subtotal, total=subtotal), _payment())
    assert split.hotel_commission_minor + split.pga_commission_minor + split.net_to_operator_minor == split.gross_minor


def test_rates_come_from_the_booking_not_the_current_partner():
    order = _order(hotel=1500, pga=2500)
    split = partner_split(order, _payment())
    assert (split.hotel_commission_minor, split.pga_commission_minor) == (1_500, 2_500)


def test_tagging_copies_name_and_rates():
    order = SimpleNamespace(partner_id=None, partner_name_snapshot=None, partner_hotel_bps=None, partner_pga_bps=None)
    partner = SimpleNamespace(id=uuid.uuid4(), name="Four Points", hotel_commission_bps=2000, pga_commission_bps=3000)
    tag_order(order, partner)
    assert (order.partner_id, order.partner_name_snapshot, order.partner_hotel_bps, order.partner_pga_bps) == (
        partner.id, "Four Points", 2000, 3000
    )
    untouched = SimpleNamespace(partner_id=None)
    tag_order(untouched, None)
    assert untouched.partner_id is None


def test_link_codes_are_normalised():
    assert partner_code("Four Points") == "four-points"
    assert partner_code(" Sunseeker ") == "sunseeker"
    assert partner_code("Four_Points") == "four-points"


def test_unknown_or_missing_code_books_as_direct():
    db = MagicMock()
    db.scalar.return_value = None
    service = PartnerService(db, uuid.uuid4())
    assert service.active_by_code(None) is None
    assert service.active_by_code("no-such-hotel") is None


@pytest.mark.parametrize(
    "values,message",
    [
        ({"name": "Greedy", "hotel_commission_bps": 6000, "pga_commission_bps": 5000}, "100%"),
        ({"name": "Direct"}, "default"),
    ],
)
def test_invalid_partners_are_refused(values, message):
    db = MagicMock()
    with pytest.raises(ConflictError, match=message):
        PartnerService(db, uuid.uuid4()).create(values)
    db.add.assert_not_called()


def test_partner_migration_and_model_agree():
    from pathlib import Path

    from app.models.entities import BookingOrder, BookingPartner

    migration = (Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "047_booking_partners.sql").read_text()
    for column in ("partner_id", "partner_name_snapshot", "partner_hotel_bps", "partner_pga_bps"):
        assert column in BookingOrder.__table__.columns
        assert f"ADD COLUMN IF NOT EXISTS {column}" in migration
    for column in BookingPartner.__table__.columns.keys():
        assert column in migration
