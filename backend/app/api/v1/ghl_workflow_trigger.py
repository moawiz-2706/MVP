import json
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.app_session import CurrentPrincipal
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.workflow_trigger import (
    WorkflowTriggerOrderStatus,
    WorkflowTriggerRetryResponse,
    WorkflowTriggerSubscriptionRead,
)
from app.services.ghl_workflow_trigger_service import (
    SECRET_HEADER,
    SubscriptionCallbackError,
    WorkflowTriggerStatusService,
    WorkflowTriggerSubscriptionService,
)
from app.services.outbox_service import OutboxService

logger = logging.getLogger("passport.workflow_trigger")
router = APIRouter(tags=["GHL Marketplace workflow trigger"])
DB = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@router.post("/integrations/marketplace/workflow-trigger/subscription")
async def workflow_trigger_subscription(
    request: Request,
    db: DB,
    settings: AppSettings,
    secret: Annotated[str | None, Header(alias=SECRET_HEADER)] = None,
) -> JSONResponse:
    """Subscription URL of the published `passport_booking_created` trigger.

    HighLevel posts here when a workflow adds (CREATED), changes (UPDATED) or
    removes (DELETED) the trigger. This is not the app lifecycle webhook.
    """
    service = WorkflowTriggerSubscriptionService(db, settings)
    raw_body = await request.body()
    try:
        service.verify_secret(secret)
        try:
            payload: Any = json.loads(raw_body)
        except ValueError as exc:
            raise SubscriptionCallbackError("Invalid subscription payload", 400) from exc
        result = service.handle(payload, raw_body)
    except SubscriptionCallbackError as exc:
        db.rollback()
        # Never log the body: it carries the workflow's execution URL.
        logger.warning("Workflow trigger subscription refused status=%s reason=%s", exc.status_code, exc)
        return JSONResponse(status_code=exc.status_code, content={"success": False, "error": str(exc)})
    return JSONResponse(status_code=200, content=result)


def _disabled(order_id: uuid.UUID) -> dict[str, Any]:
    # With the flag off, migration 045 may not be applied yet, so its tables
    # are not queried at all.
    return {"booking_order_id": order_id, "enabled": False, "events": []}


@router.get("/ghl/workflow-triggers", response_model=list[WorkflowTriggerSubscriptionRead])
def list_workflow_trigger_subscriptions(principal: CurrentPrincipal, db: DB, settings: AppSettings):
    require_permission(principal, Permission.MANAGE_CONFIGURATION)
    if not settings.ghl_workflow_trigger_enabled:
        return []
    return WorkflowTriggerStatusService(db, principal.operator_id).subscriptions()


@router.get("/orders/{order_id}/workflow-trigger", response_model=WorkflowTriggerOrderStatus)
def order_workflow_trigger_status(
    order_id: uuid.UUID, principal: CurrentPrincipal, db: DB, settings: AppSettings
):
    require_permission(principal, Permission.VIEW_BOOKINGS)
    if not settings.ghl_workflow_trigger_enabled:
        return _disabled(order_id)
    return WorkflowTriggerStatusService(db, principal.operator_id).order_status(order_id)


@router.post("/orders/{order_id}/workflow-trigger/retry", response_model=WorkflowTriggerRetryResponse)
def retry_order_workflow_trigger(
    order_id: uuid.UUID, principal: CurrentPrincipal, db: DB, settings: AppSettings
):
    require_permission(principal, Permission.OPERATE_BOOKINGS)
    if not settings.ghl_workflow_trigger_enabled:
        return {"requeued": 0, **_disabled(order_id)}
    service = WorkflowTriggerStatusService(db, principal.operator_id)
    requeued = service.retry(order_id)
    if requeued:
        try:
            OutboxService(db, settings).process(limit=20, prefer_newest=True)
        except Exception:
            # The re-queued job stays durable; the next outbox run retries it.
            db.rollback()
            logger.exception("Inline outbox processing failed after workflow trigger retry")
    return {"requeued": requeued, **service.order_status(order_id)}
