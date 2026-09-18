import uuid
from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.schemas.common import EntityModel


STAFF_ROLES = ("Captain", "First Mate", "Guide", "Deckhand", "Instructor")
StaffRole = Literal["Captain", "First Mate", "Guide", "Deckhand", "Instructor"]


class StaffHourWrite(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def validate_order(self) -> "StaffHourWrite":
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        return self


class StaffHourRead(BaseModel):
    day_of_week: int
    start_time: time
    end_time: time


def _unique_hours(hours: list[StaffHourWrite] | None) -> list[StaffHourWrite] | None:
    if hours is not None:
        keys = [(h.day_of_week, h.start_time, h.end_time) for h in hours]
        if len(keys) != len(set(keys)):
            raise ValueError("Each working-hours interval can only be listed once")
    return hours


class StaffCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    is_active: bool = True
    hours: list[StaffHourWrite] = Field(default_factory=list, max_length=100)

    @field_validator("hours")
    @classmethod
    def unique_hours(cls, value: list[StaffHourWrite]) -> list[StaffHourWrite]:
        return _unique_hours(value) or []


class StaffUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    is_active: bool | None = None
    # When supplied, replaces the full set of weekly hours.
    hours: list[StaffHourWrite] | None = Field(default=None, max_length=100)

    @field_validator("hours")
    @classmethod
    def unique_hours(cls, value: list[StaffHourWrite] | None) -> list[StaffHourWrite] | None:
        return _unique_hours(value)


class StaffRoleUpdate(BaseModel):
    custom_role: StaffRole | None = None

    @field_validator("custom_role", mode="before")
    @classmethod
    def normalize_role_input(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("custom_role")
    @classmethod
    def normalize_role(cls, value: StaffRole | None) -> StaffRole | None:
        value = (value or "").strip()
        return value or None


class StaffRead(EntityModel):
    name: str
    email: str | None
    phone: str | None
    is_active: bool
    hours: list[StaffHourRead]
    upcoming_assignments: int = 0
    ghl_user_id: str | None = None
    ghl_user_sync_status: str = "not_requested"
    ghl_user_last_error: str | None = None
    ghl_permissions_verified_at: datetime | None = None
    custom_role: str | None = None
    availability_time_zone: str | None = None
    availability_sync_status: str = "not_requested"
    availability_last_error: str | None = None
    availability_last_synced_at: datetime | None = None


class GHLStaffDirectoryResponse(BaseModel):
    synced: int
    created: int
    updated: int
    deactivated: int = 0
    availability_synced: int = 0
    availability_failed: int = 0
    error: str | None = None


class GHLStaffDetailsResponse(BaseModel):
    staff_id: uuid.UUID
    ghl_user_id: str
    profile: dict[str, object]
    time_zone: str | None
    hours: list[StaffHourRead]
    window_start: datetime | None = None
    window_end: datetime | None = None
    window_count: int = 0
    availability_sync_status: str = "not_requested"
    availability_last_synced_at: datetime | None


class StaffAssignmentCreate(BaseModel):
    staff_id: uuid.UUID
    calendar_id: uuid.UUID
    start_at: datetime
    role: StaffRole | None = None

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role_input(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @model_validator(mode="after")
    def validate_start(self) -> "StaffAssignmentCreate":
        if self.start_at.tzinfo is None:
            raise ValueError("start_at must include an offset")
        self.role = (self.role or "").strip() or None
        return self


class StaffAssignmentUpdate(BaseModel):
    staff_id: uuid.UUID | None = None
    role: StaffRole | None = None

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: StaffRole | None) -> StaffRole | None:
        return (value or "").strip() or None


class StaffAssignmentRead(BaseModel):
    id: uuid.UUID
    staff_id: uuid.UUID
    staff_name: str
    calendar_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    role: str | None


class StaffCandidate(BaseModel):
    """Whether a staff member can be assigned to one specific slot, and why not."""

    staff_id: uuid.UUID
    name: str
    custom_role: str | None
    available: bool
    reason: str | None
