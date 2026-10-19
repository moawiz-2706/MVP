from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.app_session import SessionPrincipal
from app.core.exceptions import NotFoundError
from app.core.permissions import Permission, is_admin
from app.models.entities import (
    AppUser,
    Booking,
    BookingNote,
    BookingOrder,
    BookingWaiver,
    Calendar,
    Customer,
    GHLSyncRun,
    Operator,
    OperatorUser,
    Payment,
    Staff,
    StaffAssignment,
)
from app.schemas.auth import MeOperator, MeUser
from app.schemas.pwa import (
    PWABadgeCounts,
    PWABootstrapResponse,
    PWADashboardAlert,
    PWADashboardCounts,
    PWADashboardResponse,
    PWAUniversalSearchResponse,
    PWAUniversalSearchResult,
)
from app.services.booking_admin_service import BookingAdminService


SEARCH_TYPES = frozenset({"booking", "customer", "calendar", "staff", "payment", "waiver", "note"})


def parse_search_types(value: str | None) -> set[str]:
    """Parse a comma-delimited public query value without silently broadening it."""

    if value is None or not value.strip():
        return set(SEARCH_TYPES)
    types = {item.strip().lower() for item in value.split(",") if item.strip()}
    invalid = types - SEARCH_TYPES
    if invalid:
        raise ValueError(f"Unsupported search type: {', '.join(sorted(invalid))}")
    if not types:
        raise ValueError("At least one search type is required")
    return types


def local_day_bounds(target_date: date, time_zone: str) -> tuple[datetime, datetime]:
    """Return the UTC interval for a local calendar day, including DST-short days."""

    try:
        zone = ZoneInfo(time_zone)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    start = datetime.combine(target_date, time.min, tzinfo=zone)
    end = datetime.combine(target_date + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)


class PWAWorkspaceService:
    """Read-only, tenant-scoped API projections for the Passport Staff PWA.

    The service deliberately reuses the existing booking and configuration data. It
    does not create a second PWA database or bypass established mutation services.
    """

    def __init__(self, db: Session, principal: SessionPrincipal) -> None:
        self.db = db
        self.principal = principal
        self.operator_id = principal.operator_id

    def _identity(self) -> tuple[AppUser, OperatorUser, Operator]:
        row = self.db.execute(
            select(AppUser, OperatorUser, Operator)
            .join(
                OperatorUser,
                (OperatorUser.user_id == AppUser.id)
                & (OperatorUser.operator_id == self.operator_id),
            )
            .join(Operator, Operator.id == OperatorUser.operator_id)
            .where(
                AppUser.id == self.principal.app_user_id,
                Operator.id == self.operator_id,
                Operator.is_active.is_(True),
            )
        ).one_or_none()
        if row is None:
            raise NotFoundError("Active Passport membership not found")
        return row

    @staticmethod
    def _me(user: AppUser, membership: OperatorUser, operator: Operator) -> tuple[MeUser, MeOperator]:
        return (
            MeUser(
                id=user.id,
                ghl_user_id=user.ghl_user_id,
                name=user.name,
                email=user.email,
                role=membership.ghl_role or "staff",
                is_agency_owner=membership.is_agency_owner,
            ),
            MeOperator(
                id=operator.id,
                name=operator.name,
                slug=operator.slug,
                time_zone=(operator.time_zone or "UTC").strip() or "UTC",
                ghl_location_id=operator.ghl_location_id,
            ),
        )

    def bootstrap(self) -> PWABootstrapResponse:
        user, membership, operator = self._identity()
        me_user, me_operator = self._me(user, membership, operator)
        admin = is_admin(self.principal)
        permissions = [Permission.VIEW_BOOKINGS.value, Permission.OPERATE_BOOKINGS.value]
        if admin:
            permissions.extend(
                [
                    Permission.MANAGE_CONFIGURATION.value,
                    Permission.MANAGE_PAYMENTS.value,
                    Permission.DELETE_CONFIGURATION.value,
                ]
            )
        missing_roles = self.db.scalar(
            select(func.count(Staff.id)).where(
                Staff.operator_id == self.operator_id,
                Staff.deleted_at.is_(None),
                Staff.is_active.is_(True),
                Staff.ghl_user_id.is_not(None),
                Staff.custom_role.is_(None),
            )
        ) or 0
        sync_failures = self.db.scalar(
            select(func.count(GHLSyncRun.id)).where(
                GHLSyncRun.operator_id == self.operator_id,
                GHLSyncRun.status.in_(("failed", "partial", "manual_review")),
                GHLSyncRun.resolved_at.is_(None),
            )
        ) or 0
        return PWABootstrapResponse(
            user=me_user,
            operator=me_operator,
            permissions=permissions,
            features={
                "booking_management": True,
                "calendar_management": admin,
                "staff_assignment": True,
                "waivers": True,
                "payments": admin,
                "reports": True,
                "ghl_resync": True,
            },
            badge_counts=PWABadgeCounts(
                notifications=int(sync_failures) + int(missing_roles),
                staff_missing_roles=int(missing_roles),
            ),
        )

    def dashboard(self, target_date: date | None = None) -> PWADashboardResponse:
        _user, _membership, operator = self._identity()
        time_zone = (operator.time_zone or "UTC").strip() or "UTC"
        now = datetime.now(UTC)
        if target_date is None:
            try:
                target_date = now.astimezone(ZoneInfo(time_zone)).date()
            except ZoneInfoNotFoundError:
                target_date = now.date()
        day_start, day_end = local_day_bounds(target_date, time_zone)
        next_week_end = day_end + timedelta(days=7)
        booking_service = BookingAdminService(self.db, self.operator_id)
        today = booking_service.list(day_start, day_end)
        upcoming_window = booking_service.list(max(now, day_end), next_week_end)
        upcoming = [
            item
            for item in upcoming_window
            if item["status"] not in {"cancelled", "failed"}
        ][:10]

        active_statuses = ("pending_payment", "confirmed")
        future_conditions = [
            Booking.operator_id == self.operator_id,
            Booking.start_at >= now,
            Booking.status.in_(active_statuses),
        ]
        assignment_exists = exists(
            select(StaffAssignment.id).where(
                StaffAssignment.operator_id == Booking.operator_id,
                StaffAssignment.calendar_id == Booking.calendar_id,
                StaffAssignment.start_at <= Booking.start_at,
                StaffAssignment.end_at >= Booking.end_at,
            )
        )
        unassigned = self.db.scalar(
            select(func.count(Booking.id)).where(*future_conditions, ~assignment_exists)
        ) or 0
        pending_payment = self.db.scalar(
            select(func.count(Booking.id)).where(
                Booking.operator_id == self.operator_id,
                Booking.status == "pending_payment",
                Booking.start_at >= now,
            )
        ) or 0
        waivers_pending = self.db.scalar(
            select(func.count(BookingWaiver.id))
            .join(Booking, Booking.id == BookingWaiver.booking_id)
            .where(
                Booking.operator_id == self.operator_id,
                Booking.start_at >= now,
                Booking.status.in_(active_statuses),
                BookingWaiver.status == "pending",
            )
        ) or 0
        sync_failures = self.db.scalar(
            select(func.count(GHLSyncRun.id)).where(
                GHLSyncRun.operator_id == self.operator_id,
                GHLSyncRun.status.in_(("failed", "partial", "manual_review")),
                GHLSyncRun.resolved_at.is_(None),
            )
        ) or 0
        first = aliased(StaffAssignment)
        second = aliased(StaffAssignment)
        staff_conflicts = self.db.scalar(
            select(func.count(first.id)).select_from(first).join(
                second,
                and_(
                    second.operator_id == first.operator_id,
                    second.staff_id == first.staff_id,
                    second.id > first.id,
                    second.start_at < first.end_at,
                    second.end_at > first.start_at,
                ),
            ).where(
                first.operator_id == self.operator_id,
                first.start_at < next_week_end,
                first.end_at > day_start,
            )
        ) or 0
        counts = PWADashboardCounts(
            today=len(today),
            upcoming=len(upcoming),
            pending_payment=int(pending_payment),
            waivers_pending=int(waivers_pending),
            unassigned_bookings=int(unassigned),
            sync_failures=int(sync_failures),
            staff_conflicts=int(staff_conflicts),
        )
        attention = self._attention(counts)
        return PWADashboardResponse(
            date=target_date,
            time_zone=time_zone,
            today=today[:20],
            upcoming=upcoming,
            counts=counts,
            attention=attention,
        )

    @staticmethod
    def _attention(counts: PWADashboardCounts) -> list[PWADashboardAlert]:
        alerts: list[PWADashboardAlert] = []
        if counts.sync_failures:
            alerts.append(
                PWADashboardAlert(
                    id="sync-failures",
                    title="HighLevel synchronization needs review",
                    description=f"{counts.sync_failures} synchronization issue(s) need an operator action.",
                    href="/app/notifications",
                    severity="danger",
                )
            )
        if counts.staff_conflicts:
            alerts.append(
                PWADashboardAlert(
                    id="staff-conflicts",
                    title="Staff assignment conflict",
                    description=f"{counts.staff_conflicts} overlapping staff assignment(s) appear in the next week.",
                    href="/app/staff",
                    severity="danger",
                )
            )
        if counts.unassigned_bookings:
            alerts.append(
                PWADashboardAlert(
                    id="unassigned-bookings",
                    title="Bookings have no staff assignment",
                    description=f"{counts.unassigned_bookings} upcoming booking(s) do not yet have any staff assigned.",
                    href="/app/notifications",
                    severity="warning",
                )
            )
        if counts.waivers_pending:
            alerts.append(
                PWADashboardAlert(
                    id="waivers-pending",
                    title="Waivers are awaiting signature",
                    description=f"{counts.waivers_pending} upcoming booking(s) have a pending waiver.",
                    href="/app/bookings",
                    severity="warning",
                )
            )
        if counts.pending_payment:
            alerts.append(
                PWADashboardAlert(
                    id="payments-pending",
                    title="Payment is still pending",
                    description=f"{counts.pending_payment} upcoming booking(s) have not completed payment.",
                    href="/app/bookings",
                    severity="warning",
                )
            )
        return alerts

    def search(self, query: str, *, types: set[str], limit: int) -> PWAUniversalSearchResponse:
        needle_text = query.strip()
        if len(needle_text) < 2:
            raise ValueError("Search requires at least 2 characters")
        needle = f"%{needle_text}%"
        per_type_limit = max(1, min(limit, 10))
        results: list[PWAUniversalSearchResult] = []

        customer_match = or_(
            BookingOrder.customer_first_name.ilike(needle),
            BookingOrder.customer_last_name.ilike(needle),
            BookingOrder.customer_email.ilike(needle),
        )
        if "booking" in types:
            rows = self.db.execute(
                select(Booking, BookingOrder, Calendar)
                .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
                .join(Calendar, Calendar.id == Booking.calendar_id)
                .where(
                    Booking.operator_id == self.operator_id,
                    or_(
                        BookingOrder.public_reference.ilike(needle),
                        customer_match,
                        Calendar.name.ilike(needle),
                    ),
                )
                .order_by(Booking.start_at.desc())
                .limit(per_type_limit)
            )
            for booking, order, calendar in rows:
                results.append(
                    PWAUniversalSearchResult(
                        type="booking",
                        id=booking.id,
                        title=f"{order.customer_first_name} {order.customer_last_name}".strip() or order.public_reference,
                        subtitle=f"{order.public_reference} · {calendar.name}",
                        status=booking.status,
                        href=f"/app/bookings?booking={booking.id}",
                    )
                )

        if "customer" in types:
            rows = self.db.scalars(
                select(Customer)
                .where(
                    Customer.operator_id == self.operator_id,
                    Customer.is_active.is_(True),
                    or_(
                        Customer.first_name.ilike(needle),
                        Customer.last_name.ilike(needle),
                        Customer.email.ilike(needle),
                        Customer.phone.ilike(needle),
                    ),
                )
                .order_by(Customer.updated_at.desc())
                .limit(per_type_limit)
            )
            for customer in rows:
                results.append(
                    PWAUniversalSearchResult(
                        type="customer",
                        id=customer.id,
                        title=f"{customer.first_name} {customer.last_name}".strip(),
                        subtitle=customer.email or customer.phone,
                        status=customer.ghl_contact_sync_status,
                        href=f"/app/customers?customer={customer.id}",
                    )
                )

        if "calendar" in types:
            rows = self.db.scalars(
                select(Calendar)
                .where(
                    Calendar.operator_id == self.operator_id,
                    Calendar.deleted_at.is_(None),
                    or_(Calendar.name.ilike(needle), Calendar.slug.ilike(needle)),
                )
                .order_by(Calendar.name)
                .limit(per_type_limit)
            )
            for calendar in rows:
                results.append(
                    PWAUniversalSearchResult(
                        type="calendar",
                        id=calendar.id,
                        title=calendar.name,
                        subtitle=f"/{calendar.slug}",
                        status="active" if calendar.is_active else "inactive",
                        href="/app/calendars",
                    )
                )

        if "staff" in types:
            rows = self.db.scalars(
                select(Staff)
                .where(
                    Staff.operator_id == self.operator_id,
                    Staff.deleted_at.is_(None),
                    or_(Staff.name.ilike(needle), Staff.email.ilike(needle), Staff.phone.ilike(needle)),
                )
                .order_by(Staff.name)
                .limit(per_type_limit)
            )
            for staff in rows:
                results.append(
                    PWAUniversalSearchResult(
                        type="staff",
                        id=staff.id,
                        title=staff.name,
                        subtitle=staff.email or staff.phone or staff.custom_role,
                        status="active" if staff.is_active else "inactive",
                        href="/app/staff",
                    )
                )

        if "payment" in types:
            rows = self.db.execute(
                select(Payment, BookingOrder, Booking)
                .join(BookingOrder, BookingOrder.id == Payment.booking_order_id)
                .join(Booking, Booking.booking_order_id == BookingOrder.id)
                .where(
                    Payment.operator_id == self.operator_id,
                    or_(
                        BookingOrder.public_reference.ilike(needle),
                        Payment.stripe_payment_intent_id.ilike(needle),
                        Payment.stripe_invoice_id.ilike(needle),
                        Payment.stripe_charge_id.ilike(needle),
                    ),
                )
                .order_by(Booking.start_at.desc())
                .limit(per_type_limit)
            )
            seen_payments: set[uuid.UUID] = set()
            for payment, order, booking in rows:
                if payment.id in seen_payments:
                    continue
                seen_payments.add(payment.id)
                results.append(
                    PWAUniversalSearchResult(
                        type="payment",
                        id=payment.id,
                        title=f"Payment · {order.public_reference}",
                        subtitle=f"{payment.payment_method} · {payment.customer_total_minor / 100:.2f} {payment.currency.upper()}",
                        status=payment.status,
                        href=f"/app/bookings?booking={booking.id}",
                    )
                )

        if "waiver" in types:
            rows = self.db.execute(
                select(BookingWaiver, Booking, BookingOrder)
                .join(Booking, Booking.id == BookingWaiver.booking_id)
                .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
                .where(
                    BookingWaiver.operator_id == self.operator_id,
                    or_(BookingOrder.public_reference.ilike(needle), customer_match),
                )
                .order_by(Booking.start_at.desc())
                .limit(per_type_limit)
            )
            for waiver, booking, order in rows:
                results.append(
                    PWAUniversalSearchResult(
                        type="waiver",
                        id=waiver.id,
                        title=f"Waiver · {order.public_reference}",
                        subtitle=f"{order.customer_first_name} {order.customer_last_name}".strip(),
                        status=waiver.status,
                        href=f"/app/bookings?booking={booking.id}",
                    )
                )

        if "note" in types:
            rows = self.db.execute(
                select(BookingNote, Booking, BookingOrder)
                .join(Booking, Booking.id == BookingNote.booking_id)
                .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
                .where(
                    BookingNote.operator_id == self.operator_id,
                    BookingNote.body.ilike(needle),
                )
                .order_by(BookingNote.created_at.desc())
                .limit(per_type_limit)
            )
            for note, booking, order in rows:
                preview = " ".join(note.body.split())
                results.append(
                    PWAUniversalSearchResult(
                        type="note",
                        id=note.id,
                        title=f"Note · {order.public_reference}",
                        subtitle=(preview[:120] + "…") if len(preview) > 120 else preview,
                        status=None,
                        href=f"/app/bookings?booking={booking.id}",
                    )
                )

        return PWAUniversalSearchResponse(query=needle_text, results=results[:limit])
