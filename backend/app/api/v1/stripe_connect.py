from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.stripe import StripeConnectionStatus, StripeOnboardingResponse
from app.services.stripe_connect_service import StripeConnectService


router = APIRouter(prefix="/settings/payments/stripe", tags=["Stripe Connect"])
DB = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]


def service(db: Session, settings: Settings, principal):
    require_permission(principal, Permission.MANAGE_PAYMENTS)
    return StripeConnectService(db, settings, principal.operator_id)


@router.get("", response_model=StripeConnectionStatus)
def connection_status(principal: CurrentPrincipal, db: DB, settings: Config):
    return service(db, settings, principal).status()


@router.post("/connect", response_model=StripeOnboardingResponse)
def connect(principal: CurrentPrincipal, db: DB, settings: Config):
    return service(db, settings, principal).connect()


@router.post("/onboarding-link", response_model=StripeOnboardingResponse)
def onboarding_link(principal: CurrentPrincipal, db: DB, settings: Config):
    return service(db, settings, principal).onboarding_link()


@router.get("/status", response_model=StripeConnectionStatus)
def refresh_status(principal: CurrentPrincipal, db: DB, settings: Config):
    return service(db, settings, principal).status(refresh=True)

