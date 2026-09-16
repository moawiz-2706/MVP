from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.database import get_db
from app.core.permissions import Permission, require_permission
from app.models.entities import OperatorSettings
from app.schemas.waiver import PublicWaiver, WaiverSettings, WaiverSignRequest
from app.services.waiver_service import WaiverService

router = APIRouter(tags=["waivers"])
DB = Annotated[Session, Depends(get_db)]


# Public: the secret token in the link is the customer's credential.


@router.get("/public/waivers/{token}", response_model=PublicWaiver)
def public_waiver(token: str, db: DB):
    return WaiverService(db).public_view(token)


@router.post("/public/waivers/{token}/sign", response_model=PublicWaiver)
def sign_waiver(token: str, data: WaiverSignRequest, request: Request, db: DB):
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else None)
    return WaiverService(db).sign(token, data, ip=ip, user_agent=request.headers.get("user-agent"))


# Operator settings: anyone on the team can read; admins can change.


@router.get("/settings/waiver", response_model=WaiverSettings)
def get_waiver_settings(principal: CurrentPrincipal, db: DB):
    settings = db.get(OperatorSettings, principal.operator_id)
    if settings is None:
        return WaiverSettings()
    return WaiverSettings(**{key: getattr(settings, key) for key in WaiverSettings.model_fields})


@router.put("/settings/waiver", response_model=WaiverSettings)
def update_waiver_settings(data: WaiverSettings, principal: CurrentPrincipal, db: DB):
    require_permission(principal, Permission.MANAGE_CONFIGURATION)
    settings = db.get(OperatorSettings, principal.operator_id)
    if settings is None:
        settings = OperatorSettings(operator_id=principal.operator_id)
        db.add(settings)
    for key, value in data.model_dump().items():
        setattr(settings, key, value)
    db.commit()
    return data
