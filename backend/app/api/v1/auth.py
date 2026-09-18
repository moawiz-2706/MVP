from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.entities import AppUser, Operator, OperatorUser
from app.schemas.auth import GHLSessionRequest, GHLSessionResponse, MeOperator, MeResponse, MeUser
from app.services.ghl_auth_service import GHLAuthService


router = APIRouter(tags=["authentication"])


@router.post("/auth/ghl-session", response_model=GHLSessionResponse)
def create_ghl_session(
    request: GHLSessionRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GHLSessionResponse:
    try:
        token, expires_in = GHLAuthService(db, settings).create_session_from_context(
            request.encrypted_data
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GHLSessionResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=MeResponse)
def me(principal: CurrentPrincipal, db: Annotated[Session, Depends(get_db)]) -> MeResponse:
    row = db.execute(
        select(AppUser, OperatorUser, Operator)
        .join(
            OperatorUser,
            (OperatorUser.user_id == AppUser.id)
            & (OperatorUser.operator_id == principal.operator_id),
        )
        .join(Operator, Operator.id == OperatorUser.operator_id)
        .where(
            AppUser.id == principal.app_user_id,
            Operator.id == principal.operator_id,
            Operator.is_active.is_(True),
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="Application session is no longer valid")
    user, membership, operator = row
    return MeResponse(
        user=MeUser(
            id=user.id,
            ghl_user_id=user.ghl_user_id,
            name=user.name,
            email=user.email,
            role=membership.ghl_role or principal.role,
            is_agency_owner=membership.is_agency_owner,
        ),
        operator=MeOperator(
            id=operator.id,
            name=operator.name,
            slug=operator.slug,
            time_zone=(operator.time_zone or "UTC").strip() or "UTC",
            ghl_location_id=operator.ghl_location_id,
        ),
    )
