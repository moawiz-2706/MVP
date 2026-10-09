import pytest

from app.core.exceptions import ConflictError
from app.services.order_service import OrderService


def test_private_staff_payment_methods_are_explicit():
    assert OrderService.payment_mode(5000, None, requested_payment_method="card", allow_override=True) == (True, False, True, "card")
    assert OrderService.payment_mode(5000, None, requested_payment_method="invoice", allow_override=True) == (True, True, False, "invoice")
    assert OrderService.payment_mode(5000, None, requested_payment_method="none", allow_override=True) == (False, False, False, "none")


def test_public_checkout_cannot_use_staff_payment_override():
    assert OrderService.payment_mode(5000, None, requested_payment_method="none", allow_override=False) == (True, False, True, "card")


def test_unknown_payment_method_is_rejected_for_private_booking():
    with pytest.raises(ConflictError):
        OrderService.payment_mode(5000, None, requested_payment_method="cash", allow_override=True)
