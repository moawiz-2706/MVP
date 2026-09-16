from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

CUSTOMER_MARKUP_BPS = 1300
OPERATOR_TRANSFER_MARKUP_BPS = 700
PLATFORM_FEE_LABEL = "Platform Fee & Taxes"
_BPS = Decimal(10_000)


def apply_basis_points(amount_minor: int, basis_points: int) -> int:
    if amount_minor < 0:
        raise ValueError("Money amount cannot be negative")
    result = (Decimal(amount_minor) * Decimal(basis_points) / _BPS).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(result)


@dataclass(frozen=True, slots=True)
class PaymentBreakdown:
    subtotal_minor: int
    platform_fee_and_taxes_minor: int
    customer_total_minor: int
    operator_transfer_minor: int
    platform_gross_retained_minor: int


def calculate_payment(subtotal_minor: int) -> PaymentBreakdown:
    platform_fee = apply_basis_points(subtotal_minor, CUSTOMER_MARKUP_BPS)
    operator_bonus = apply_basis_points(subtotal_minor, OPERATOR_TRANSFER_MARKUP_BPS)
    customer_total = subtotal_minor + platform_fee
    operator_transfer = subtotal_minor + operator_bonus
    return PaymentBreakdown(
        subtotal_minor=subtotal_minor,
        platform_fee_and_taxes_minor=platform_fee,
        customer_total_minor=customer_total,
        operator_transfer_minor=operator_transfer,
        platform_gross_retained_minor=customer_total - operator_transfer,
    )

