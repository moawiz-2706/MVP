from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class PartnerWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # Link code used in `?partner=`; derived from the name when omitted.
    code: str | None = Field(default=None, max_length=80)
    hotel_commission_bps: int = Field(default=2000, ge=0, le=10_000)
    pga_commission_bps: int = Field(default=3000, ge=0, le=10_000)
    is_active: bool = True


class PartnerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = Field(default=None, max_length=80)
    hotel_commission_bps: int | None = Field(default=None, ge=0, le=10_000)
    pga_commission_bps: int | None = Field(default=None, ge=0, le=10_000)
    is_active: bool | None = None


class PartnerRead(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    hotel_commission_bps: int
    pga_commission_bps: int
    is_active: bool
    booking_link: str
    created_at: datetime


class PartnerCommissionRow(BaseModel):
    """One partner's split for tours in the period. Amounts are minor units."""

    source_partner: str
    partner_id: uuid.UUID | None
    bookings: int
    guests: int
    gross_minor: int
    hotel_commission_minor: int
    pga_commission_minor: int
    net_to_operator_minor: int
    currency: str


class PartnerCommissionReport(BaseModel):
    start_date: date
    end_date: date
    rows: list[PartnerCommissionRow]
