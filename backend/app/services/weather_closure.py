from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import Calendar, CalendarBookingPolicy, WeatherClosureEvent
from app.schemas.fareharbor_replica import WeatherClosureRequest
from app.schemas.pwa import PWAClosurePreview, PWACloseDepartureRequest, PWACloseDepartureResponse
from app.services.manifest_service import ManifestService


def _departure(db: Session, operator_id: uuid.UUID, calendar_id: uuid.UUID, start_at: datetime):
    calendar = db.scalar(select(Calendar).where(Calendar.id == calendar_id, Calendar.operator_id == operator_id))
    if calendar is None:
        raise NotFoundError("Calendar not found")
    start_at = start_at.astimezone(UTC)
    manifest = ManifestService(db, operator_id).manifest(calendar_id, start_at)
    end_at = max(manifest.end_at, start_at + timedelta(minutes=calendar.duration_minutes))
    return calendar, start_at, end_at, manifest


def _existing_closure(db, operator_id, calendar_id, start_at, end_at) -> WeatherClosureEvent | None:
    return db.scalar(
        select(WeatherClosureEvent).where(
            WeatherClosureEvent.operator_id == operator_id,
            WeatherClosureEvent.calendar_id == calendar_id,
            WeatherClosureEvent.start_at == start_at,
            WeatherClosureEvent.end_at == end_at,
        )
    )


def closure_preview(
    db: Session, operator_id: uuid.UUID, calendar_id: uuid.UUID, start_at: datetime
) -> PWAClosurePreview:
    calendar, start_at, end_at, manifest = _departure(db, operator_id, calendar_id, start_at)
    policy = db.scalar(
        select(CalendarBookingPolicy)
        .where(
            CalendarBookingPolicy.operator_id == operator_id,
            CalendarBookingPolicy.calendar_id == calendar.id,
            CalendarBookingPolicy.active.is_(True),
        )
        .order_by(CalendarBookingPolicy.version.desc())
    )
    return PWAClosurePreview(
        manifest=manifest,
        # The calendar's configured weather policy; the client approves it there.
        default_refund_mode=policy.weather_refund_mode if policy else "full_refund",
        already_closed=_existing_closure(db, operator_id, calendar.id, start_at, end_at) is not None,
    )


def close_departure(
    db: Session, operator_id: uuid.UUID, user_id: uuid.UUID, data: PWACloseDepartureRequest
) -> PWACloseDepartureResponse:
    calendar, start_at, end_at, manifest = _departure(db, operator_id, data.calendar_id, data.start_at)
    first_attempt = _existing_closure(db, operator_id, calendar.id, start_at, end_at) is None
    if first_attempt and len(manifest.bookings) != data.expected_bookings:
        raise ConflictError(
            f"This departure now has {len(manifest.bookings)} bookings, not {data.expected_bookings}. "
            "Review the preview again before closing it."
        )
    from app.services.fareharbor_replica_service import FareHarborReplicaService

    result = FareHarborReplicaService(db, operator_id).weather_closure(
        WeatherClosureRequest(
            calendar_id=calendar.id,
            start_at=start_at,
            end_at=end_at,
            reason=data.reason,
            refund_mode=data.refund_mode,
        ),
        user_id,
    )
    return PWACloseDepartureResponse(
        closure_id=result["closure_id"],
        cancelled_bookings=result["affected_bookings"],
        refund_mode=result["refund_mode"],
        failed=result["failed"],
    )
