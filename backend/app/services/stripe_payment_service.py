import stripe

from app.core.config import Settings


class StripePaymentService:
    def __init__(self, settings: Settings) -> None:
        if not settings.stripe_secret_key:
            raise RuntimeError("STRIPE_SECRET_KEY is not configured")
        self.client = stripe.StripeClient(settings.stripe_secret_key, max_network_retries=2)

    def create_payment_intent(
        self,
        *,
        order_id: str,
        operator_id: str,
        public_reference: str,
        amount_minor: int,
        currency: str,
        receipt_email: str,
        idempotency_key: str | None = None,
    ) -> tuple[str, str]:
        intent = self.client.v1.payment_intents.create(
            {
                "amount": amount_minor,
                "currency": currency,
                "payment_method_types": ["card"],
                "receipt_email": receipt_email,
                "transfer_group": f"booking_order_{public_reference}",
                "metadata": {
                    "booking_order_id": order_id,
                    "operator_id": operator_id,
                    "public_reference": public_reference,
                },
            },
            {"idempotency_key": idempotency_key or f"booking_order:{order_id}:payment_intent"},
        )
        if not intent.client_secret:
            raise RuntimeError("Stripe did not return a PaymentIntent client secret")
        return intent.id, intent.client_secret

    def retrieve_payment_intent(self, payment_intent_id: str):
        return self.client.v1.payment_intents.retrieve(payment_intent_id, {"expand": ["latest_charge"]})

    def find_payment_intent_for_order(self, order_id: str):
        """Find a provider-created intent after a network timeout.

        Stripe metadata is written before the provider call and the local
        request has a stable idempotency key. Search is deliberately narrowed
        to the immutable order identity; callers still validate amount,
        currency, and operator metadata before attaching the result.
        """
        result = self.client.v1.payment_intents.search({
            "query": f"metadata['booking_order_id']:'{order_id}'",
            "limit": 10,
        })
        data = result.to_dict_recursive() if hasattr(result, "to_dict_recursive") else dict(result)
        matches = data.get("data", [])
        return matches[0] if matches else None
