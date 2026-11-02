from __future__ import annotations

import uuid
from datetime import date, datetime
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


class PWADepartureResource(BaseModel):
    """Inventory for one resource type at one departure; unlike units never combine."""

    resource_id: uuid.UUID
    name: str
    total: int = Field(ge=0)
    confirmed: int = Field(ge=0)
    held: int = Field(ge=0)
    remaining: int = Field(ge=0)


class PWADepartureBooking(BaseModel):
    id: uuid.UUID
    public_reference: str
    lead_name: str
    status: str
    payment_status: str | None
    payment_method: str | None
    units: int


class PWADepartureStaff(BaseModel):
    assignment_id: uuid.UUID
    staff_id: uuid.UUID
    staff_name: str
    role: str | None


class PWADeparture(BaseModel):
    calendar_id: uuid.UUID
    calendar_name: str
    category_color: str | None
    start_at: datetime
    end_at: datetime
    source: Literal["scheduled", "pushed", "unscheduled"]
    blocked: bool
    resources: list[PWADepartureResource]
    bookings: list[PWADepartureBooking]
    staff: list[PWADepartureStaff]
    booked_units: int = Field(ge=0)


class PWADeparturesResponse(BaseModel):
    date: date
    time_zone: str
    departures: list[PWADeparture]


class PWAManifestParticipant(BaseModel):
    id: uuid.UUID
    sequence: int
    name: str
    is_minor: bool
    guardian_name: str | None
    phone: str | None
    email: str | None
    checked_in_at: datetime | None


class PWAManifestBooking(BaseModel):
    id: uuid.UUID
    public_reference: str
    lead_name: str
    lead_phone: str | None
    lead_email: str
    status: str
    payment_status: str | None
    payment_method: str | None
    units: int
    waiver_status: Literal["signed", "pending", "none"]
    participants: list[PWAManifestParticipant]


class PWAManifestResponse(BaseModel):
    calendar_id: uuid.UUID
    calendar_name: str
    start_at: datetime
    end_at: datetime
    time_zone: str
    expected_units: int = Field(ge=0)
    named_participants: int = Field(ge=0)
    checked_in: int = Field(ge=0)
    staff: list[PWADepartureStaff]
    bookings: list[PWAManifestBooking]


class PWACheckInRequest(BaseModel):
    checked_in: bool = True


class PWAClosurePreview(BaseModel):
    manifest: PWAManifestResponse
    default_refund_mode: Literal["full_refund", "credit", "manual_review", "no_refund"]
    already_closed: bool


class PWACloseDepartureRequest(BaseModel):
    calendar_id: uuid.UUID
    start_at: datetime
    reason: str = Field(min_length=3, max_length=500)
    refund_mode: Literal["full_refund", "credit", "manual_review", "no_refund"]
    # The number of bookings the operator saw in the preview; a mismatch means
    # the departure changed in between and the preview must be reviewed again.
    expected_bookings: int = Field(ge=0)


class PWACloseDepartureResponse(BaseModel):
    closure_id: uuid.UUID
    cancelled_bookings: int
    refund_mode: str
    failed: list[dict[str, str]]
