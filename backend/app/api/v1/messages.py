from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.database import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.messages import (
    MessageTemplatePreviewRequest,
    MessageTemplatePreviewResponse,
    MessageTemplateRead,
    MessageTemplateUpdate,
)
from app.services.message_template_service import MessageTemplateError, MessageTemplateService

router = APIRouter(tags=["messages"])
DB = Annotated[Session, Depends(get_db)]


def _service(db: Session, principal: CurrentPrincipal) -> MessageTemplateService:
    return MessageTemplateService(db, principal.operator_id)


def _invalid(exc: MessageTemplateError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/settings/messages", response_model=list[MessageTemplateRead])
def list_message_templates(principal: CurrentPrincipal, db: DB):
    require_permission(principal, Permission.VIEW_BOOKINGS)
    return _service(db, principal).list_effective()


@router.put("/settings/messages/{event_type}", response_model=MessageTemplateRead)
def update_message_template(
    event_type: str,
    data: MessageTemplateUpdate,
    principal: CurrentPrincipal,
    db: DB,
):
    require_permission(principal, Permission.MANAGE_CONFIGURATION)
    try:
        return _service(db, principal).save(
            event_type,
            enabled=data.enabled,
            subject=data.subject_template,
            body=data.body_template,
            user_id=principal.app_user_id,
        )
    except MessageTemplateError as exc:
        raise _invalid(exc) from exc


@router.delete("/settings/messages/{event_type}", status_code=status.HTTP_204_NO_CONTENT)
def reset_message_template(event_type: str, principal: CurrentPrincipal, db: DB) -> None:
    require_permission(principal, Permission.MANAGE_CONFIGURATION)
    try:
        service = _service(db, principal)
        service.event_type(event_type)
        service.reset(event_type)
    except MessageTemplateError as exc:
        raise _invalid(exc) from exc


@router.post("/settings/messages/preview", response_model=MessageTemplatePreviewResponse)
def preview_message_template(
    data: MessageTemplatePreviewRequest,
    principal: CurrentPrincipal,
    db: DB,
):
    require_permission(principal, Permission.VIEW_BOOKINGS)
    try:
        return MessageTemplateService.preview(
            data.event_type,
            data.subject_template,
            data.body_template,
        )
    except MessageTemplateError as exc:
        raise _invalid(exc) from exc
