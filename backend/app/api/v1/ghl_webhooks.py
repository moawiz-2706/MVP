from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.services.ghl_webhook_service import GHLWebhookService

router = APIRouter(prefix="/integrations/marketplace", tags=["GHL lifecycle webhooks"])


@router.post("/webhook")
async def ghl_lifecycle_webhook(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    signature: Annotated[str | None, Header(alias="X-GHL-Signature")] = None,
) -> dict[str, bool]:
    raw_body = await request.body()
    try:
        service = GHLWebhookService(db, settings)
        service.verify_signature(raw_body, signature)
        payload = await request.json()
        service.process(payload, raw_body)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid HighLevel lifecycle webhook") from exc
    return {"received": True}
