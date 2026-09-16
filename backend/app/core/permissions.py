from enum import StrEnum

from fastapi import HTTPException

from app.core.app_session import SessionPrincipal


class Permission(StrEnum):
    VIEW_BOOKINGS = "view_bookings"
    OPERATE_BOOKINGS = "operate_bookings"
    MANAGE_CONFIGURATION = "manage_configuration"
    MANAGE_PAYMENTS = "manage_payments"
    DELETE_CONFIGURATION = "delete_configuration"


_ADMIN_ROLES = {"admin", "administrator", "agency_admin"}


def is_admin(principal: SessionPrincipal) -> bool:
    return principal.is_agency_owner or principal.role.lower() in _ADMIN_ROLES


def require_permission(principal: SessionPrincipal, permission: Permission) -> None:
    generally_allowed = {Permission.VIEW_BOOKINGS, Permission.OPERATE_BOOKINGS}
    if permission in generally_allowed or is_admin(principal):
        return
    raise HTTPException(status_code=403, detail="You do not have permission for this action")

