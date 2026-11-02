from datetime import date

from pydantic import BaseModel


class ReportSummary(BaseModel):
    start_date: date
    end_date: date
    total_bookings: int
    confirmed_bookings: int
    pending_payment_bookings: int
    cancelled_bookings: int
    completed_bookings: int
    units_booked: int
    gross_sales_minor: int
    booking_fees_minor: int
    taxes_minor: int
    upcoming_bookings: int
    failed_sync_jobs: int


class CreatorReportRow(BaseModel):
    """Bookings attributed to whoever created them. Not a commission figure."""

    booking_source: str | None
    staff_id: str | None
    user_id: str | None
    creator_name: str
    orders: int
    confirmed_orders: int
    cancelled_orders: int
    gross_minor: int
    refunded_minor: int
    currency: str


class CreatorReport(BaseModel):
    start_date: date
    end_date: date
    rows: list[CreatorReportRow]
