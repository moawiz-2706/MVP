from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.auth import MeOperator, MeUser
from app.schemas.booking import BookingListItem


class PWABadgeCounts(BaseModel):
    """Small counts used by the PWA shell; this is not a notification ledger."""

    notifications: int = Field(ge=0)
    staff_missing_roles: int = Field(ge=0)


class PWABootstrapResponse(BaseModel):
    """One tenant-scoped response for the PWA shell after authentication."""

    user: MeUser
    operator: MeOperator
    permissions: list[str]
    features: dict[str, bool]
    badge_counts: PWABadgeCounts


class PWADashboardCounts(BaseModel):
    today: int = Field(ge=0)
    upcoming: int = Field(ge=0)
    pending_payment: int = Field(ge=0)
    waivers_pending: int = Field(ge=0)
    unassigned_bookings: int = Field(ge=0)
    sync_failures: int = Field(ge=0)
    staff_conflicts: int = Field(ge=0)


class PWADashboardAlert(BaseModel):
    id: str
    title: str
    description: str
    href: str
    severity: Literal["warning", "danger"]


class PWADashboardResponse(BaseModel):
    date: date
    time_zone: str
    today: list[BookingListItem]
    upcoming: list[BookingListItem]
    counts: PWADashboardCounts
    attention: list[PWADashboardAlert]


class PWAUniversalSearchResult(BaseModel):
    type: Literal["booking", "customer", "calendar", "staff", "payment", "waiver", "note"]
    id: uuid.UUID
    title: str
    subtitle: str | None = None
    status: str | None = None
    href: str


class PWAUniversalSearchResponse(BaseModel):
    query: str
    results: list[PWAUniversalSearchResult]
