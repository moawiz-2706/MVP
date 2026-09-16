import base64
import uuid
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.config import Settings
from app.services.ghl_webhook_service import GHLWebhookService
from app.services.public_access_service import PublicAccessService
from app.services.stripe_webhook_service import StripeWebhookService


def test_public_access_digest_is_not_the_raw_token() -> None:
    token = "test-public-capability"
    digest = PublicAccessService.digest(token)
    assert digest != token
    assert len(digest) == 64


def test_stripe_mismatch_quarantines_wrong_amount_currency_and_metadata() -> None:
    payment = SimpleNamespace(customer_total_minor=1200, currency="usd")
    order = SimpleNamespace(id=uuid.uuid4(), operator_id=uuid.uuid4(), public_reference="PASSPORT-1")
    mismatches = StripeWebhookService._payment_mismatches(
        payment,
        order,
        {
            "status": "succeeded",
            "amount": 100,
            "amount_received": 100,
            "currency": "eur",
            "metadata": {
                "booking_order_id": str(uuid.uuid4()),
                "public_reference": "wrong",
            },
        },
        {},
    )
    assert {"amount", "amount_received", "currency", "booking_order_id", "public_reference"}.issubset(
        mismatches
    )


def test_highlevel_webhook_ed25519_signature_verifies() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes_raw()
    body = b'{"type":"UNINSTALL","locationId":"loc-1"}'
    signature = base64.b64encode(private_key.sign(body)).decode()
    settings = Settings(ghl_webhook_public_key=base64.b64encode(public_key).decode())
    GHLWebhookService(None, settings).verify_signature(body, signature)
    with pytest.raises(ValueError, match="Invalid HighLevel webhook signature"):
        GHLWebhookService(None, settings).verify_signature(body + b"x", signature)


def test_production_settings_reject_missing_secrets() -> None:
    settings = Settings(environment="production")
    with pytest.raises(RuntimeError, match="Missing required production settings"):
        settings.validate_runtime()
