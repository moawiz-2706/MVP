import pytest

from app.utils.money import apply_basis_points, calculate_payment


def test_required_payment_example() -> None:
    result = calculate_payment(20_000)
    assert result.subtotal_minor == 20_000
    assert result.platform_fee_and_taxes_minor == 2_600
    assert result.customer_total_minor == 22_600
    assert result.operator_transfer_minor == 21_400
    assert result.platform_gross_retained_minor == 1_200


def test_round_half_up_on_half_minor_unit() -> None:
    assert apply_basis_points(5, 1_000) == 1


def test_negative_money_rejected() -> None:
    with pytest.raises(ValueError):
        calculate_payment(-1)


# --- Spec §156: payment math -------------------------------------------------


def test_spec156_28_subtotal_is_unit_price_times_units() -> None:
    # base_price_minor 5000 * 4 units = 20000 subtotal.
    base_price_minor, units = 5_000, 4
    assert calculate_payment(base_price_minor * units).subtotal_minor == 20_000


def test_spec156_29_customer_total_adds_thirteen_percent() -> None:
    result = calculate_payment(20_000)
    assert result.platform_fee_and_taxes_minor == 2_600
    assert result.customer_total_minor == 22_600


def test_spec156_30_operator_transfer_adds_seven_percent() -> None:
    result = calculate_payment(20_000)
    assert result.operator_transfer_minor == 21_400


def test_spec156_31_platform_gross_is_six_percent() -> None:
    result = calculate_payment(20_000)
    # 22600 - 21400 = 1200 = 6% of subtotal, before Stripe costs.
    assert result.platform_gross_retained_minor == 1_200
    assert result.platform_gross_retained_minor == apply_basis_points(20_000, 600)


def test_spec156_32_round_half_up_on_odd_minor_units() -> None:
    # 12,350 * 13% = 1605.5 -> 1606 (half rounds up); * 7% = 864.5 -> 865.
    result = calculate_payment(12_350)
    assert result.platform_fee_and_taxes_minor == 1_606
    assert result.operator_transfer_minor - 12_350 == 865
    # Fee is always at least the transfer bonus, so platform retention never goes negative.
    for subtotal in range(0, 5_000, 37):
        breakdown = calculate_payment(subtotal)
        assert breakdown.platform_gross_retained_minor >= 0


def test_payment_math_is_deterministic() -> None:
    assert calculate_payment(9_999) == calculate_payment(9_999)

