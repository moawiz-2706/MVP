from datetime import UTC, date, datetime, time, timedelta
import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.database import get_db
from app.core.permissions import Permission, require_permission
from app.models.entities import AppUser, Booking, BookingOrder, OutboxJob, Payment, Staff
from app.schemas.reports import CreatorReport, CreatorReportRow, ReportSummary

router = APIRouter(tags=["reports"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/reports/summary", response_model=ReportSummary)
def report_summary(
    principal: CurrentPrincipal,
    db: DB,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
) -> ReportSummary:
    require_permission(principal, Permission.VIEW_BOOKINGS)
    today = datetime.now(UTC).date()
    start = start_date or today
    end = end_date or (today + timedelta(days=30))
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    start_at = datetime.combine(start, time.min, tzinfo=UTC)
    end_at = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
    rows = list(
        db.execute(
            select(Booking, BookingOrder)
            .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
            .where(
                Booking.operator_id == principal.operator_id,
                Booking.start_at >= start_at,
                Booking.start_at < end_at,
            )
        )
    )
    active = [booking for booking, _order in rows if booking.status not in {"cancelled", "failed"}]
    failed_jobs = db.scalar(
        select(func.count(OutboxJob.id)).where(
            OutboxJob.operator_id == principal.operator_id,
            OutboxJob.status == "failed",
        )
    ) or 0
    return ReportSummary(
        start_date=start,
        end_date=end,
        total_bookings=len(rows),
        confirmed_bookings=sum(booking.status == "confirmed" for booking, _order in rows),
        pending_payment_bookings=sum(booking.status == "pending_payment" for booking, _order in rows),
        cancelled_bookings=sum(booking.status == "cancelled" for booking, _order in rows),
        completed_bookings=sum(booking.status == "completed" for booking, _order in rows),
        units_booked=sum(booking.units for booking in active),
        gross_sales_minor=sum(order.customer_total_minor for booking, order in rows if booking.status not in {"cancelled", "failed"}),
        booking_fees_minor=sum(booking.booking_fee_minor for booking in active),
        taxes_minor=sum(booking.tax_minor for booking in active),
        upcoming_bookings=sum(booking.status in {"confirmed", "pending_payment"} and booking.start_at >= datetime.now(UTC) for booking, _order in rows),
        failed_sync_jobs=failed_jobs,
    )


@router.get("/reports/bookings.csv")
def booking_export(
    principal: CurrentPrincipal,
    db: DB,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
) -> StreamingResponse:
    require_permission(principal, Permission.VIEW_BOOKINGS)
    today = datetime.now(UTC).date()
    start = start_date or today
    end = end_date or (today + timedelta(days=30))
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    rows = db.execute(
        select(Booking, BookingOrder)
        .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
        .where(
            Booking.operator_id == principal.operator_id,
            Booking.start_at >= datetime.combine(start, time.min, tzinfo=UTC),
            Booking.start_at < datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC),
        )
        .order_by(Booking.start_at, Booking.id)
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["public_reference", "booking_id", "calendar", "start_at", "end_at", "units", "status", "customer_name", "customer_email", "subtotal_minor", "fees_and_taxes_minor", "total_minor"])
    for booking, order in rows:
        writer.writerow([
            order.public_reference,
            booking.id,
            booking.calendar_name_snapshot,
            booking.start_at.isoformat(),
            booking.end_at.isoformat(),
            booking.units,
            booking.status,
            f"{order.customer_first_name} {order.customer_last_name}",
            order.customer_email,
            order.subtotal_minor,
            order.platform_fee_and_taxes_minor,
            order.customer_total_minor,
        ])
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="passport-bookings-{start}-{end}.csv"'},
    )


CONFIRMED_ORDER_STATUSES = ("confirmed", "paid", "partially_refunded")
SOURCE_LABELS = {
    "public": "Public booking page",
    "staff_link": "Staff booking link",
    "pwa": "Staff app",
    "desktop": "Passport desktop",
}


@router.get("/reports/bookings-by-creator", response_model=CreatorReport)
def bookings_by_creator(
    principal: CurrentPrincipal,
    db: DB,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
) -> CreatorReport:
    """Orders created in the range, grouped by who created them and how.

    Admin only: per-staff sales totals are the input to commission and must
    not be visible to other staff. Amounts are order totals, not commission.
    """

    require_permission(principal, Permission.MANAGE_PAYMENTS)
    today = datetime.now(UTC).date()
    end = end_date or today
    start = start_date or (end - timedelta(days=30))
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    start_at = datetime.combine(start, time.min, tzinfo=UTC)
    end_at = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
    rows = db.execute(
        select(
            BookingOrder.booking_source,
            BookingOrder.created_by_staff_id,
            BookingOrder.created_by_user_id,
            BookingOrder.currency,
            func.count(BookingOrder.id),
            func.count(BookingOrder.id).filter(BookingOrder.status.in_(CONFIRMED_ORDER_STATUSES)),
            func.count(BookingOrder.id).filter(BookingOrder.status.in_(("cancelled", "expired", "refunded"))),
            func.coalesce(
                func.sum(BookingOrder.customer_total_minor).filter(
                    BookingOrder.status.in_(CONFIRMED_ORDER_STATUSES)
                ),
                0,
            ),
            func.coalesce(func.sum(Payment.refunded_minor), 0),
        )
        .outerjoin(Payment, Payment.booking_order_id == BookingOrder.id)
        .where(
            BookingOrder.operator_id == principal.operator_id,
            BookingOrder.created_at >= start_at,
            BookingOrder.created_at < end_at,
        )
        .group_by(
            BookingOrder.booking_source,
            BookingOrder.created_by_staff_id,
            BookingOrder.created_by_user_id,
            BookingOrder.currency,
        )
    ).all()
    staff_names = dict(
        db.execute(
            select(Staff.id, Staff.name).where(
                Staff.id.in_([row[1] for row in rows if row[1] is not None])
            )
        ).all()
    )
    user_names = {
        user_id: name or email
        for user_id, name, email in db.execute(
            select(AppUser.id, AppUser.name, AppUser.email).where(
                AppUser.id.in_([row[2] for row in rows if row[2] is not None])
            )
        ).all()
    }
    result = []
    for source, staff_id, user_id, currency, orders, confirmed, cancelled, gross, refunded in rows:
        name = staff_names.get(staff_id) or user_names.get(user_id)
        if name is None:
            name = SOURCE_LABELS.get(source or "", "Created before attribution")
        result.append(
            CreatorReportRow(
                booking_source=source,
                staff_id=str(staff_id) if staff_id else None,
                user_id=str(user_id) if user_id else None,
                creator_name=name,
                orders=orders,
                confirmed_orders=confirmed,
                cancelled_orders=cancelled,
                gross_minor=int(gross),
                refunded_minor=int(refunded),
                currency=currency,
            )
        )
    result.sort(key=lambda row: (-row.gross_minor, row.creator_name.lower()))
    return CreatorReport(start_date=start, end_date=end, rows=result)
