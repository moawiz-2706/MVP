from types import SimpleNamespace

from app.api.v1 import payouts
from app.models.entities import Calendar, OperatorSettings
from app.services.order_service import DEFAULT_PAYOUT_SHARE_BPS, connected_payout_minor
from app.utils.money import calculate_payment


def _item(subtotal, included=True):
    return SimpleNamespace(line_subtotal_minor=subtotal, calendar=SimpleNamespace(payout_included=included))


def test_connected_account_gets_its_share_of_the_ticket_price_only():
    # $100 ticket + $7 tax: 80% of the ticket goes out, the tax stays.
    payout = connected_payout_minor([_item(10_000)], 8_000)
    money = calculate_payment(10_000, booking_fee_minor=0, tax_minor=700, operator_transfer_minor=payout)
    assert money.customer_total_minor == 10_700
    assert money.operator_transfer_minor == 8_000
    assert money.platform_gross_retained_minor == 2_700


def test_excluded_calendars_keep_everything_in_the_main_account():
    payout = connected_payout_minor([_item(10_000, included=True), _item(5_000, included=False)], 8_000)
    assert payout == 8_000
    money = calculate_payment(15_000, booking_fee_minor=0, tax_minor=0, operator_transfer_minor=0)
    assert money.operator_transfer_minor == 0 and money.platform_gross_retained_minor == 15_000


def test_split_never_exceeds_the_amount_charged():
    money = calculate_payment(10_000, booking_fee_minor=0, tax_minor=0, operator_transfer_minor=99_999)
    assert money.operator_transfer_minor == money.customer_total_minor


def test_default_share_and_columns_match_migration_052():
    assert DEFAULT_PAYOUT_SHARE_BPS == 8_000
    assert OperatorSettings.__table__.c.payout_share_bps.server_default.arg == "8000"
    assert Calendar.__table__.c.payout_included.server_default.arg == "true"


def test_settings_routes_are_registered_and_validate_the_percentage():
    paths = {(route.path, tuple(sorted(route.methods))) for route in payouts.router.routes}
    assert ("/settings/payments/payouts", ("GET",)) in paths
    assert ("/settings/payments/payouts", ("PUT",)) in paths
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        payouts.PayoutSettingsUpdate(payout_share_bps=10_001)
    assert payouts.PayoutSettingsUpdate(payout_share_bps=8_000).calendars == []
