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
