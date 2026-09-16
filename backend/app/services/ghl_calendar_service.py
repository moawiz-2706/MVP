from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Calendar, GHLCalendarMapping, Operator
from app.services.ghl_client import GHLClient


class GHLCalendarService:
    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id
        self.settings = get_settings()
        self.client = GHLClient(operator_id)

    def sync(self, calendar_id: uuid.UUID) -> str | None:
        if not self.settings.ghl_calendar_sync_enabled:
            return None
        row = self.db.execute(
            select(Calendar, Operator)
            .join(Operator, Operator.id == Calendar.operator_id)
            .where(Calendar.id == calendar_id, Calendar.operator_id == self.operator_id)
        ).one_or_none()
        if row is None:
            raise RuntimeError("GHL calendar source not found")
        calendar, operator = row
        mapping = self.db.scalar(
            select(GHLCalendarMapping).where(
                GHLCalendarMapping.operator_id == self.operator_id,
                GHLCalendarMapping.calendar_id == calendar.id,
            ).with_for_update()
        )
        if mapping is None:
            mapping = GHLCalendarMapping(
                operator_id=self.operator_id,
                calendar_id=calendar.id,
                desired_revision=1,
                status="pending",
            )
            self.db.add(mapping)
            self.db.flush()
        body = {
            "locationId": operator.ghl_location_id,
            "name": f"(PASSPORT) {calendar.name}",
            "calendarType": "event",
            "description": f"Passport calendar: {calendar.id}",
            "slotDuration": calendar.duration_minutes,
            "slotDurationUnit": "mins",
            "slotInterval": calendar.slot_interval_minutes,
            "slotIntervalUnit": "mins",
            "allowReschedule": False,
            "allowCancellation": False,
        }
        try:
            if mapping.ghl_calendar_id:
                result = self.client.request(
                    "PUT",
                    f"/calendars/{mapping.ghl_calendar_id}",
                    version="v3",
                    json=body,
                )
            else:
                result = self.client.request("POST", "/calendars/", version="v3", json=body)
            remote = result.get("calendar", result)
            remote_id = remote.get("id") if isinstance(remote, dict) else None
            if not remote_id and mapping.ghl_calendar_id:
                remote_id = mapping.ghl_calendar_id
            if not remote_id:
                raise RuntimeError("HighLevel did not return an Event Calendar ID")
            mapping.ghl_calendar_id = str(remote_id)
            mapping.applied_revision = mapping.desired_revision
            mapping.status = "synced"
            mapping.last_error = None
            self.db.commit()
            return mapping.ghl_calendar_id
        except Exception as exc:
            mapping.status = "failed"
            mapping.last_error = str(exc)[:2000]
            self.db.commit()
            raise
