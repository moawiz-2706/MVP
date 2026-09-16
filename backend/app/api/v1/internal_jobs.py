import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.services.outbox_service import OutboxService
from app.services.reminder_service import ReminderService


router = APIRouter(prefix="/internal", tags=["internal"])
DB = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
# Stop claiming new work well inside the function time limit so a batch is
# never cut off mid-send; anything left is picked up by the next run.
DRAIN_BUDGET_SECONDS = 45


def _authorize(settings: Settings, authorization: str | None, x_cron_secret: str | None) -> None:
    supplied = x_cron_secret
    if authorization and authorization.startswith("Bearer "):
        supplied = authorization.removeprefix("Bearer ")
    if not settings.cron_secret or not supplied or not hmac.compare_digest(
        supplied.encode(), settings.cron_secret.encode()
    ):
        raise HTTPException(status_code=401, detail="Invalid cron authorization")


@router.post("/process-outbox")
def process_outbox(
    db: DB,
    settings: AppSettings,
    authorization: Annotated[str | None, Header()] = None,
    x_cron_secret: Annotated[str | None, Header()] = None,
) -> dict[str, int]:
    _authorize(settings, authorization, x_cron_secret)
    return OutboxService(db, settings).process(limit=20)


@router.get("/cron/daily")
def daily_cron(
    db: DB,
    settings: AppSettings,
    authorization: Annotated[str | None, Header()] = None,
    x_cron_secret: Annotated[str | None, Header()] = None,
) -> dict[str, int]:
    """Vercel Cron entry point: GET with `Authorization: Bearer $CRON_SECRET`.

    Queues reminders for bookings and staff slots starting later today or
    tomorrow (operator-local), then works the outbox so they, and any earlier
    failures due for retry, are sent. Safe to invoke more than once a day.
    """
    _authorize(settings, authorization, x_cron_secret)
    queued = ReminderService(db).enqueue()
    return {**queued, **OutboxService(db, settings).drain(budget_seconds=DRAIN_BUDGET_SECONDS)}
