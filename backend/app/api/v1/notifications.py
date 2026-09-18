from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.database import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.notifications import NotificationsResponse
from app.services.notification_service import NotificationService

router = APIRouter(tags=["notifications"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/notifications", response_model=NotificationsResponse)
def notifications(principal: CurrentPrincipal, db: DB) -> NotificationsResponse:
    require_permission(principal, Permission.VIEW_BOOKINGS)
    return NotificationService(db, principal.operator_id).list()
