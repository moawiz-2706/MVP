from typing import Annotated

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.services.stripe_webhook_service import StripeWebhookService

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
    StripeWebhookService(db, settings).process(event.to_dict_recursive())
    return {"received": True}
