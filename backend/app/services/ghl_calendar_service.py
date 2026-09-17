from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import (
    Calendar,
    DepartureLocation,
    GHLCalendarMapping,
    Operator,
)
from app.services.ghl_client import GHLAPIError, GHLClient


class GHLCalendarService:
    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id
        self.settings = get_settings()
        self.client = GHLClient(operator_id)

    @staticmethod
    def _schedule_rules() -> list[dict[str, Any]]:
        """Keep HighLevel open 24/7; Passport remains the slot authority."""
        return [
            {
                "type": "wday",
                "day": day,
                # HighLevel represents a full 24-hour day as 00:00 -> 00:00.
                "intervals": [{"from": "00:00", "to": "00:00"}],
            }
            for day in (
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            )
        ]

    def _sync_schedule(self, calendar: Calendar, operator: Operator, remote_id: str) -> None:
        body = {"rules": self._schedule_rules(), "timezone": operator.time_zone}
        path = f"/calendars/schedules/event-calendar/{remote_id}"
        try:
            self.client.request("PUT", path, version="v3", json=body)
        except GHLAPIError as exc:
            if exc.status_code != 404:
                raise
            self.client.request("POST", path, version="v3", json=body)

    def sync(self, calendar_id: uuid.UUID) -> str | None:
        if not self.settings.ghl_calendar_sync_enabled:
            return None
        row = self.db.execute(
            select(Calendar, Operator, DepartureLocation)
            .join(Operator, Operator.id == Calendar.operator_id)
            .outerjoin(DepartureLocation, DepartureLocation.id == Calendar.departure_location_id)
            .where(Calendar.id == calendar_id, Calendar.operator_id == self.operator_id)
        ).one_or_none()
        if row is None:
            raise RuntimeError("GHL calendar source not found")
        calendar, operator, departure_location = row
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
        common_body = {
            "name": f"(PASSPORT) {calendar.name}",
            "isActive": calendar.is_active,
            "description": f"Passport calendar: {calendar.id}",
            "locationConfigurations": (
                [
                    {
                        "kind": "custom",
                        "location": f"{departure_location.name} — {departure_location.address}",
                    }
                ]
                if departure_location is not None
                else []
            ),
            "slotDuration": calendar.duration_minutes,
            "slotDurationUnit": "mins",
            "slotInterval": calendar.slot_interval_minutes,
            "slotIntervalUnit": "mins",
            "allowReschedule": False,
            "allowCancellation": False,
        }
        try:
            if mapping.ghl_calendar_id:
                # HighLevel's Update Calendar schema does not accept
                # locationId; the subaccount location is immutable after
                # creation. The Passport departure location is represented
                # by locationConfigurations and can be updated here.
                result = self.client.request(
                    "PUT",
                    f"/calendars/{mapping.ghl_calendar_id}",
                    version="v3",
                    json=common_body,
                )
            else:
                result = self.client.request(
                    "POST",
                    "/calendars/",
                    version="v3",
                    json={
                        "locationId": operator.ghl_location_id,
                        "calendarType": "event",
                        **common_body,
                    },
                )
            remote = result.get("calendar", result)
            remote_id = remote.get("id") if isinstance(remote, dict) else None
            if not remote_id and mapping.ghl_calendar_id:
                remote_id = mapping.ghl_calendar_id
            if not remote_id:
                raise RuntimeError("HighLevel did not return an Event Calendar ID")
            self._sync_schedule(calendar, operator, str(remote_id))
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

    def delete(self, calendar_id: uuid.UUID, remote_id: str | None = None) -> None:
        mapping = self.db.scalar(
            select(GHLCalendarMapping).where(
                GHLCalendarMapping.operator_id == self.operator_id,
                GHLCalendarMapping.calendar_id == calendar_id,
            )
        )
        remote_id = remote_id or (mapping.ghl_calendar_id if mapping else None)
        if not remote_id:
            return
        try:
            self.client.request("DELETE", f"/calendars/{remote_id}", version="v3")
        except GHLAPIError as exc:
            if exc.status_code != 404:
                raise
        if mapping is not None:
            mapping.ghl_calendar_id = None
            mapping.status = "deleted"
            mapping.last_error = None
            self.db.commit()
