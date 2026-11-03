import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.permissions import Permission, is_admin, require_permission
from app.models.entities import BookingPartner, Operator
from app.schemas.partners import (
    PartnerCommissionReport,
    PartnerRead,
    PartnerUpdate,
    PartnerWrite,
)
from app.services.partner_service import PartnerService, commission_report

router = APIRouter(tags=["partners"])
DB = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def _read(partner: BookingPartner, operator: Operator, settings: Settings) -> dict:
    return {
        "id": partner.id,
        "name": partner.name,
        "code": partner.code,
        "hotel_commission_bps": partner.hotel_commission_bps,
        "pga_commission_bps": partner.pga_commission_bps,
        "is_active": partner.is_active,
        "booking_link": f"{settings.frontend_url.rstrip('/')}/book/{operator.slug}?partner={partner.code}",
        "created_at": partner.created_at,
    }


def _operator(db: Session, principal) -> Operator:
    return db.scalar(select(Operator).where(Operator.id == principal.operator_id))


@router.get("/partners", response_model=list[PartnerRead])
def list_partners(principal: CurrentPrincipal, db: DB, settings: AppSettings):
    """All staff can pick a partner when booking; only admins see switched-off ones."""
    require_permission(principal, Permission.OPERATE_BOOKINGS)
    operator = _operator(db, principal)
    partners = PartnerService(db, principal.operator_id).list(include_inactive=is_admin(principal))
    return [_read(partner, operator, settings) for partner in partners]


@router.post("/partners", response_model=PartnerRead, status_code=status.HTTP_201_CREATED)
def create_partner(data: PartnerWrite, principal: CurrentPrincipal, db: DB, settings: AppSettings):
    require_permission(principal, Permission.MANAGE_CONFIGURATION)
    partner = PartnerService(db, principal.operator_id).create(data.model_dump())
    return _read(partner, _operator(db, principal), settings)


@router.patch("/partners/{partner_id}", response_model=PartnerRead)
def update_partner(
    partner_id: uuid.UUID, data: PartnerUpdate, principal: CurrentPrincipal, db: DB, settings: AppSettings
):
    require_permission(principal, Permission.MANAGE_CONFIGURATION)
    partner = PartnerService(db, principal.operator_id).update(partner_id, data.model_dump(exclude_unset=True))
    return _read(partner, _operator(db, principal), settings)


@router.delete("/partners/{partner_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_partner(partner_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> Response:
    require_permission(principal, Permission.DELETE_CONFIGURATION)
    PartnerService(db, principal.operator_id).delete(partner_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/reports/partner-commissions", response_model=PartnerCommissionReport)
def partner_commissions(
    principal: CurrentPrincipal,
    db: DB,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
):
    """Hotel and PGA commission per partner, by tour date. Admin only."""
    require_permission(principal, Permission.MANAGE_PAYMENTS)
    operator = _operator(db, principal)
    today = datetime.now(UTC).date()
    end = end_date or today
    start = start_date or (end - timedelta(days=30))
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    rows = commission_report(db, principal.operator_id, start, end, operator.time_zone or "UTC")
    return {"start_date": start, "end_date": end, "rows": rows}
