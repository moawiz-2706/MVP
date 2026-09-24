import logging
from typing import Annotated

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.services.outbox_service import OutboxService
from app.services.stripe_webhook_service import StripeWebhookService

logger = logging.getLogger("passport.stripe_webhook")

router = APIRouter(tags=["Stripe webhooks"])


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, bool]:
    if not stripe_signature or not settings.stripe_webhook_secret:
        raise HTTPException(status_code=400, detail="Missing Stripe webhook signature")
    raw_body = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            raw_body, stripe_signature, settings.stripe_webhook_secret
        )
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature") from exc
    StripeWebhookService(db).process(event.to_dict_recursive())
    # Best effort: run the jobs this event just enqueued (operator transfer, GHL
    # contact sync, confirmation email) so they land in seconds instead of waiting
    # for the periodic sweep. This must never fail the webhook — the payment and
    # booking are already committed, and anything that does not succeed here stays
    # queued with backoff for the outbox to retry.
    try:
        OutboxService(db, settings).process(limit=100, prefer_newest=True)
    except Exception:
        logger.exception("Inline outbox processing failed; jobs remain queued for retry")
    return {"received": True}
