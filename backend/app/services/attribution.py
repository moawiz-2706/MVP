from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.app_session import SessionPrincipal
from app.models.entities import AppUser, Staff
from app.services.order_service import BookingAttribution


def staff_attribution(db: Session, principal: SessionPrincipal, client: str | None) -> BookingAttribution:
    """Attribute a booking created by a signed-in Passport user.

    The client header only distinguishes the standalone PWA from the embedded
    desktop for reporting; it grants nothing. The creating staff record is the
    operator's staff member linked to the same HighLevel user, when one exists.
    """

    ghl_user_id = db.scalar(select(AppUser.ghl_user_id).where(AppUser.id == principal.app_user_id))
    staff_id = None
    if ghl_user_id:
        staff_id = db.scalar(
            select(Staff.id).where(
                Staff.operator_id == principal.operator_id,
                Staff.ghl_user_id == ghl_user_id,
                Staff.deleted_at.is_(None),
            )
        )
    return BookingAttribution(
        source="pwa" if (client or "").strip().lower() == "pwa" else "desktop",
        created_by_user_id=principal.app_user_id,
        created_by_staff_id=staff_id,
    )
