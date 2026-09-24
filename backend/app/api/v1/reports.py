from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.app_session import CurrentPrincipal
from app.core.database import get_db
from app.core.permissions import Permission, require_permission
from app.models.entities import Booking, BookingOrder, OutboxJob
from app.schemas.reports import ReportSummary

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
