from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.permissions import Permission, require_permission
from app.models.entities import OutboxJob, Staff
from app.schemas.staff import GHLStaffDirectoryResponse
from app.services.ghl_staff_user_service import GHLStaffUserService

router = APIRouter(tags=["staff-ghl"])
DB = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


class PermissionVerification(BaseModel):
    confirmed: bool


@router.post("/staff-ghl/directory/sync", response_model=GHLStaffDirectoryResponse)
def sync_staff_directory(principal: CurrentPrincipal, db: DB):
    require_permission(principal, Permission.MANAGE_CONFIGURATION)
    return GHLStaffUserService(db, principal.operator_id).sync_directory()


def _staff(db: Session, operator_id: uuid.UUID, staff_id: uuid.UUID) -> Staff:
    staff = db.scalar(
        select(Staff).where(
            Staff.id == staff_id,
            Staff.operator_id == operator_id,
            Staff.deleted_at.is_(None),
        )
    )
    if staff is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Staff member not found")
    return staff


@router.post("/staff/{staff_id}/ghl-user/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_staff_ghl_user(
    staff_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DB,
    settings: AppSettings,
) -> dict[str, str | None]:
    require_permission(principal, Permission.MANAGE_CONFIGURATION)
    staff = _staff(db, principal.operator_id, staff_id)
    key = f"staff:{staff.id}:ghl_user:retry"
    existing = db.scalar(select(OutboxJob).where(OutboxJob.idempotency_key == key))
    if existing is None:
        db.add(
            OutboxJob(
                operator_id=principal.operator_id,
                job_type="ghl_sync_staff_user",
                idempotency_key=key,
                payload={"staff_id": str(staff.id)},
                status="pending",
            )
        )
    elif existing.status in {"failed", "dead"}:
        existing.status = "pending"
        existing.attempt_count = 0
        existing.next_attempt_at = None
        existing.last_error = None
        existing.lease_owner = None
        existing.lease_expires_at = None
    staff.ghl_user_sync_status = "pending"
    staff.ghl_user_last_error = None
    db.commit()
    return {
        "ghl_user_id": staff.ghl_user_id,
        "ghl_user_sync_status": staff.ghl_user_sync_status,
        "ghl_user_last_error": staff.ghl_user_last_error,
        "ghl_permissions_verified_at": (
            staff.ghl_permissions_verified_at.isoformat()
            if staff.ghl_permissions_verified_at
            else None
        ),
    }


@router.post("/staff/{staff_id}/ghl-user/verify-permissions")
def verify_staff_ghl_permissions(
    data: PermissionVerification,
    staff_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DB,
) -> dict[str, str | None]:
    require_permission(principal, Permission.MANAGE_CONFIGURATION)
    return GHLStaffUserService(db, principal.operator_id).verify_permissions(
        staff_id, confirmed=data.confirmed
    )
