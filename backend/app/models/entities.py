import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    DDL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Operator(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "operators"

    ghl_location_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    time_zone: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    public_booking_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class GHLInstallation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ghl_installations"

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, unique=True
    )
    location_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    company_id: Mapped[str | None] = mapped_column(Text)
    installed_by_user_id: Mapped[str | None] = mapped_column(Text)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_installed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    authz_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lifecycle_status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    granted_scopes: Mapped[list | None] = mapped_column(JSONB)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    uninstalled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppUser(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "app_users"

    ghl_user_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)


class OperatorUser(TimestampMixin, Base):
    __tablename__ = "operator_users"

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_users.id"), primary_key=True
    )
    ghl_role: Mapped[str | None] = mapped_column(Text)
    is_agency_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class OperatorSettings(TimestampMixin, Base):
    __tablename__ = "operator_settings"

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), primary_key=True
    )
    confirmation_email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    confirmation_email_from: Mapped[str | None] = mapped_column(Text)
    confirmation_email_subject: Mapped[str] = mapped_column(
        Text, nullable=False, default="Booking Confirmation"
    )
    # Waiver shown to customers after booking; no text means waivers are off.
    waiver_title: Mapped[str | None] = mapped_column(Text)
    waiver_website: Mapped[str | None] = mapped_column(Text)
    waiver_text: Mapped[str | None] = mapped_column(Text)
    waiver_opt_in_label: Mapped[str | None] = mapped_column(Text)


class DepartureLocation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "departure_locations"

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CalendarCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "calendar_categories"
    __table_args__ = (
        Index(
            "uq_calendar_categories_active_slug",
            "operator_id",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    display_color: Mapped[str | None] = mapped_column(String(20))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Calendar(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "calendars"
    __table_args__ = (
        Index(
            "uq_calendars_active_slug",
            "operator_id",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint("duration_minutes > 0", name="duration_positive"),
        CheckConstraint("slot_interval_minutes > 0", name="slot_interval_positive"),
        CheckConstraint(
            "max_units_per_booking IS NULL OR max_units_per_booking > 0",
            name="max_units_positive",
        ),
        CheckConstraint("base_price_minor >= 0", name="base_price_nonnegative"),
        CheckConstraint(
            "availability_mode IN ('day_wise', 'date_wise', 'pushed')",
            name="availability_mode_valid",
        ),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, index=True
    )
    calendar_category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calendar_categories.id"), index=True
    )
    departure_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departure_locations.id"), index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    public_booking_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    slot_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    max_units_per_booking: Mapped[int | None] = mapped_column(Integer)
    base_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="usd")
    # Exactly one mode governs availability; the other mode's rows are ignored.
    availability_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="day_wise"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CalendarHour(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "calendar_hours"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("start_time < end_time", name="time_order"),
        UniqueConstraint("calendar_id", "day_of_week", "start_time", "end_time"),
    )

    calendar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False
    )
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)


class CalendarDateHour(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Date-wise opening hours: one row per (date range, time interval)."""

    __tablename__ = "calendar_date_hours"
    __table_args__ = (
        CheckConstraint("start_date <= end_date", name="date_order"),
        CheckConstraint("start_time < end_time", name="time_order"),
        Index("ix_calendar_date_hours_calendar_range", "calendar_id", "start_date", "end_date"),
    )

    calendar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)


class CalendarPushedSlot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Pushed-mode availability: one explicitly offered start instant.

    The end is always derived as start + calendar.duration_minutes, so a later
    duration change applies to every pushed slot consistently.
    """

    __tablename__ = "calendar_pushed_slots"
    __table_args__ = (UniqueConstraint("calendar_id", "start_at"),)

    calendar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CalendarBlock(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "calendar_blocks"
    __table_args__ = (CheckConstraint("start_at < end_at", name="time_order"),)

    calendar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)


class Resource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resources"
    __table_args__ = (CheckConstraint("quantity >= 0", name="quantity_nonnegative"),)

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CalendarResource(Base):
    __tablename__ = "calendar_resources"
    __table_args__ = (
        CheckConstraint("default_quantity_per_unit > 0", name="quantity_positive"),
    )

    calendar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calendars.id", ondelete="CASCADE"), primary_key=True
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.id"), primary_key=True, index=True
    )
    default_quantity_per_unit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Staff(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "staff"

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ghl_contact_id: Mapped[str | None] = mapped_column(Text)


class StaffHour(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Weekly working hours in operator-local wall time (like calendar_hours)."""

    __tablename__ = "staff_hours"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("start_time < end_time", name="time_order"),
        UniqueConstraint("staff_id", "day_of_week", "start_time", "end_time"),
    )

    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id", ondelete="CASCADE"), nullable=False
    )
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)


class StaffAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A staff member working one calendar time slot; busy for [start_at, end_at)."""

    __tablename__ = "staff_assignments"
    __table_args__ = (
        CheckConstraint("start_at < end_at", name="time_order"),
        Index("ix_staff_assignments_staff_interval", "staff_id", "start_at", "end_at"),
        Index("ix_staff_assignments_operator_interval", "operator_id", "start_at", "end_at"),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id"), nullable=False
    )
    calendar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calendars.id"), nullable=False
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    role: Mapped[str | None] = mapped_column(Text)


class BookingOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "booking_orders"
    __table_args__ = (
        CheckConstraint("subtotal_minor >= 0", name="subtotal_nonnegative"),
        CheckConstraint("platform_fee_and_taxes_minor >= 0", name="fee_nonnegative"),
        CheckConstraint("customer_total_minor >= 0", name="total_nonnegative"),
        CheckConstraint("operator_transfer_minor >= 0", name="transfer_nonnegative"),
        CheckConstraint("platform_gross_retained_minor >= 0", name="retained_nonnegative"),
        CheckConstraint(
            "status IN ('pending_payment','paid','confirmed','expired','cancelled',"
            "'partially_refunded','refunded','exception')",
            name="status_valid",
        ),
        CheckConstraint(
            "ghl_contact_sync_status IN ('pending','synced','failed','disabled')",
            name="contact_sync_status_valid",
        ),
        CheckConstraint(
            "ghl_confirmation_email_status IN ('pending','sent','failed','disabled')",
            name="email_status_valid",
        ),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, index=True
    )
    public_reference: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    customer_first_name: Mapped[str] = mapped_column(Text, nullable=False)
    customer_last_name: Mapped[str] = mapped_column(Text, nullable=False)
    customer_email: Mapped[str] = mapped_column(Text, nullable=False)
    customer_phone: Mapped[str | None] = mapped_column(Text)
    ghl_contact_id: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="usd")
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_fee_and_taxes_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    operator_transfer_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_gross_retained_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checkout_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    checkout_request_hash: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    ghl_contact_sync_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    ghl_confirmation_email_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    ghl_conversation_id: Mapped[str | None] = mapped_column(Text)
    ghl_message_id: Mapped[str | None] = mapped_column(Text)
    ghl_email_message_id: Mapped[str | None] = mapped_column(Text)


class Booking(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("start_at < end_at", name="time_order"),
        CheckConstraint("units > 0", name="units_positive"),
        CheckConstraint("base_price_minor >= 0", name="base_price_nonnegative"),
        CheckConstraint(
            "status IN ('pending_payment','confirmed','cancelled','completed','no_show','failed')",
            name="status_valid",
        ),
        Index("ix_bookings_operator_interval", "operator_id", "start_at", "end_at"),
        Index("ix_bookings_calendar_interval", "calendar_id", "start_at", "end_at"),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False
    )
    booking_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("booking_orders.id"), nullable=False, index=True
    )
    calendar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calendars.id"), nullable=False
    )
    departure_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departure_locations.id")
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    base_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    calendar_name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    departure_location_name_snapshot: Mapped[str | None] = mapped_column(Text)
    departure_location_address_snapshot: Mapped[str | None] = mapped_column(Text)


class BookingResource(Base):
    __tablename__ = "booking_resources"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)

    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"), primary_key=True
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.id"), primary_key=True, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)


class BookingWaiver(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One waiver per booking, signed once by the lead participant or guardian.

    Signing snapshots the exact waiver text and activity; a database trigger then
    rejects any further change or deletion (see the listeners at the end of this
    module and migration 007).
    """

    __tablename__ = "booking_waivers"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'signed')", name="status_valid"),
        CheckConstraint(
            "status <> 'signed' OR (signed_at IS NOT NULL AND waiver_text IS NOT NULL"
            " AND details IS NOT NULL AND signature_png IS NOT NULL)",
            name="signed_complete",
        ),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, index=True
    )
    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id"), nullable=False, unique=True
    )
    # Secret link credential sent to the customer; never sequential.
    token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    public_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signer_ip: Mapped[str | None] = mapped_column(Text)
    signer_user_agent: Mapped[str | None] = mapped_column(Text)
    waiver_title: Mapped[str | None] = mapped_column(Text)
    waiver_text: Mapped[str | None] = mapped_column(Text)
    activity_name: Mapped[str | None] = mapped_column(Text)
    activity_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict | None] = mapped_column(JSONB)
    signature_png: Mapped[str | None] = mapped_column(Text)


class BookingNote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Internal note on a booking, visible only to the operator's team."""

    __tablename__ = "booking_notes"
    __table_args__ = (
        CheckConstraint("char_length(body) BETWEEN 1 AND 5000", name="body_length"),
        Index("ix_booking_notes_booking_created", "booking_id", "created_at"),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False
    )
    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id"), nullable=False
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_users.id")
    )
    author_name: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)


class StripeConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "stripe_connections"

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, unique=True
    )
    stripe_account_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    account_type: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(String(2))
    details_submitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payouts_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    charges_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    transfers_capability_status: Mapped[str | None] = mapped_column(Text)
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requires_payment','processing','succeeded','failed',"
            "'partially_refunded','refunded')",
            name="status_valid",
        ),
        CheckConstraint("refunded_minor >= 0", name="refunded_nonnegative"),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, index=True
    )
    booking_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("booking_orders.id"), nullable=False, unique=True
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(Text, unique=True)
    stripe_charge_id: Mapped[str | None] = mapped_column(Text, unique=True)
    stripe_balance_transaction_id: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_fee_and_taxes_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    operator_transfer_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_gross_retained_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stripe_fee_minor: Mapped[int | None] = mapped_column(BigInteger)
    platform_net_minor: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reconciliation_status: Mapped[str | None] = mapped_column(String(30))
    observed_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    observed_amount_received_minor: Mapped[int | None] = mapped_column(BigInteger)
    observed_currency: Mapped[str | None] = mapped_column(String(3))
    stripe_livemode: Mapped[bool | None] = mapped_column(Boolean)
    stripe_account_id: Mapped[str | None] = mapped_column(Text)
    provider_unknown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StripeTransfer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "stripe_transfers"
    __table_args__ = (
        UniqueConstraint("payment_id", name="uq_stripe_transfers_payment"),
        CheckConstraint("amount_minor >= 0", name="amount_nonnegative"),
        CheckConstraint("reversed_minor >= 0", name="reversed_nonnegative"),
        CheckConstraint(
            "status IN ('pending','created','failed','partially_reversed','reversed')",
            name="status_valid",
        ),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), nullable=False
    )
    stripe_transfer_id: Mapped[str | None] = mapped_column(Text, unique=True)
    stripe_connected_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    stripe_source_transaction_id: Mapped[str] = mapped_column(Text, nullable=False)
    transfer_group: Mapped[str | None] = mapped_column(Text)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    reversed_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class StripeWebhookEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "stripe_webhook_events"

    stripe_event_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PaymentIntentRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_intent_requests"
    __table_args__ = (
        UniqueConstraint("operator_id", "checkout_key", name="uq_payment_intent_requests_checkout"),
        UniqueConstraint("payment_id", name="uq_payment_intent_requests_payment"),
        CheckConstraint(
            "status IN ('pending','processing','succeeded','provider_unknown','failed','quarantined')",
            name="payment_intent_request_status_valid",
        ),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, index=True
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), nullable=False
    )
    checkout_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    request_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(Text, unique=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    provider_unknown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BookingFinancialAllocation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "booking_financial_allocations"
    __table_args__ = (
        UniqueConstraint("booking_id", name="uq_booking_financial_allocations_booking"),
        CheckConstraint("customer_refund_minor >= 0", name="allocation_refund_nonnegative"),
        CheckConstraint("operator_recovery_minor >= 0", name="allocation_recovery_nonnegative"),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, index=True
    )
    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id"), nullable=False
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), nullable=False
    )
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_refund_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    operator_recovery_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    allocation_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)


class PaymentRefundAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_refund_attempts"
    __table_args__ = (
        UniqueConstraint("payment_id", "scope_key", name="uq_payment_refund_attempt_scope"),
        CheckConstraint(
            "status IN ('requested','pending','succeeded','failed','canceled','requires_action')",
            name="refund_attempt_status_valid",
        ),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, index=True
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), nullable=False
    )
    scope_key: Mapped[str] = mapped_column(Text, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    stripe_refund_id: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="requested")
    failure_reason: Mapped[str | None] = mapped_column(Text)


class TransferReversalAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "transfer_reversal_attempts"
    __table_args__ = (
        UniqueConstraint("transfer_id", "scope_key", name="uq_transfer_reversal_attempt_scope"),
        CheckConstraint(
            "status IN ('requested','pending','succeeded','failed','blocked','not_transferred')",
            name="reversal_attempt_status_valid",
        ),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, index=True
    )
    transfer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stripe_transfers.id"), nullable=False
    )
    scope_key: Mapped[str] = mapped_column(Text, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    stripe_reversal_id: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="requested")
    failure_reason: Mapped[str | None] = mapped_column(Text)


class PublicAccessCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "public_access_credentials"
    __table_args__ = (
        UniqueConstraint("token_digest", name="uq_public_access_credentials_digest"),
        CheckConstraint(
            "purpose IN ('order_status','waiver_sign','waiver_view','waiver_view_sensitive')",
            name="public_access_purpose_valid",
        ),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("booking_orders.id")
    )
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id")
    )
    token_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GHLOAuthState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ghl_oauth_states"

    state_digest: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    flow: Mapped[str] = mapped_column(String(30), nullable=False, default="app_start")
    expected_location_id: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GHLWebhookEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ghl_webhook_events"

    provider_event_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    location_id: Mapped[str | None] = mapped_column(Text, index=True)
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    payload: Mapped[dict | None] = mapped_column(JSONB)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GHLCalendarMapping(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ghl_calendar_mappings"
    __table_args__ = (UniqueConstraint("operator_id", "calendar_id", name="uq_ghl_calendar_mapping"),)

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, index=True
    )
    calendar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calendars.id"), nullable=False
    )
    ghl_calendar_id: Mapped[str | None] = mapped_column(Text, unique=True)
    desired_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    applied_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    last_error: Mapped[str | None] = mapped_column(Text)


class GHLAppointmentMapping(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ghl_appointment_mappings"
    __table_args__ = (UniqueConstraint("operator_id", "booking_id", name="uq_ghl_appointment_mapping"),)

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False, index=True
    )
    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id"), nullable=False
    )
    ghl_calendar_mapping_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ghl_calendar_mappings.id"), nullable=False
    )
    ghl_event_id: Mapped[str | None] = mapped_column(Text, unique=True)
    desired_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    applied_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    payload_hash: Mapped[str | None] = mapped_column(String(128))
    last_error: Mapped[str | None] = mapped_column(Text)


class PublicRateLimitBucket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "public_rate_limit_buckets"

    bucket_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class OutboxJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "outbox_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','processing','completed','failed','dead')", name="status_valid"
        ),
        # Mirrors migrations 001/006/007. Keep in sync: tests build tables from these
        # models, so a job type missing here would otherwise only fail in production.
        CheckConstraint(
            "job_type IN ('stripe_create_transfer','ghl_upsert_contact',"
            "'ghl_send_confirmation_email','ghl_booking_reminder','ghl_upsert_staff_contact',"
            "'ghl_staff_assigned_email','ghl_staff_reminder','ghl_staff_unassigned_email',"
            "'stripe_create_refund','stripe_create_transfer_reversal','stripe_reconcile_payment_intent',"
            "'ghl_sync_calendar','ghl_delete_calendar','ghl_sync_appointment','ghl_cancel_appointment')",
            name="job_type_valid",
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        Index("ix_outbox_jobs_ready", "status", "next_attempt_at"),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False
    )
    booking_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("booking_orders.id")
    )
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# Signed waivers are a legal record. Migration 007 installs this trigger in
# production; tests build tables from these models, so attach it here as well.
event.listen(
    BookingWaiver.__table__,
    "after_create",
    DDL(
        "CREATE OR REPLACE FUNCTION prevent_signed_waiver_change() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "IF OLD.status = 'signed' THEN RAISE EXCEPTION 'signed waivers are locked'; END IF; "
        "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END; $$"
    ).execute_if(dialect="postgresql"),
)
event.listen(
    BookingWaiver.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER trg_booking_waiver_lock BEFORE UPDATE OR DELETE ON booking_waivers "
        "FOR EACH ROW EXECUTE FUNCTION prevent_signed_waiver_change()"
    ).execute_if(dialect="postgresql"),
)
