from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import (
    Calendar,
    CalendarDateHour,
    CalendarHour,
    CalendarPushedSlot,
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

    def _schedule_rules(self, calendar: Calendar) -> list[dict[str, Any]]:
        if calendar.availability_mode == "day_wise":
            by_day: dict[int, list[dict[str, str]]] = defaultdict(list)
            rows = self.db.scalars(
                select(CalendarHour)
                .where(CalendarHour.calendar_id == calendar.id)
                .order_by(CalendarHour.day_of_week, CalendarHour.start_time)
            )
            for row in rows:
                by_day[row.day_of_week].append(
                    {
                        "from": row.start_time.strftime("%H:%M"),
                        "to": row.end_time.strftime("%H:%M"),
                    }
                )
            weekdays = [
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ]
            return [
                {"type": "wday", "day": weekdays[day], "intervals": intervals}
                for day, intervals in sorted(by_day.items())
            ]

        if calendar.availability_mode == "date_wise":
            rows = self.db.scalars(
                select(CalendarDateHour)
                .where(CalendarDateHour.calendar_id == calendar.id)
                .order_by(CalendarDateHour.start_date, CalendarDateHour.start_time)
            )
            by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
            for row in rows:
                current = row.start_date
                while current <= row.end_date:
                    by_date[current.isoformat()].append(
                        {
                            "from": row.start_time.strftime("%H:%M"),
                            "to": row.end_time.strftime("%H:%M"),
                        }
                    )
                    current += timedelta(days=1)
            return [
                {"type": "date", "date": day, "intervals": intervals}
                for day, intervals in sorted(by_date.items())
            ]

        rows = self.db.scalars(
            select(CalendarPushedSlot)
            .where(
                CalendarPushedSlot.calendar_id == calendar.id,
                CalendarPushedSlot.start_at >= datetime.now(UTC),
            )
            .order_by(CalendarPushedSlot.start_at)
        )
        rules: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            local_start = row.start_at.astimezone(ZoneInfo(self._operator_zone(calendar)))
            local_end = local_start + timedelta(minutes=calendar.duration_minutes)
            rules[local_start.date().isoformat()].append(
                {"from": local_start.strftime("%H:%M"), "to": local_end.strftime("%H:%M")}
            )
        return [
            {"type": "date", "date": day, "intervals": intervals}
            for day, intervals in sorted(rules.items())
        ]

    def _operator_zone(self, calendar: Calendar) -> str:
        return str(
            self.db.scalar(select(Operator.time_zone).where(Operator.id == calendar.operator_id))
            or "UTC"
        )

    def _sync_schedule(self, calendar: Calendar, operator: Operator, remote_id: str) -> None:
        body = {"rules": self._schedule_rules(calendar), "timezone": operator.time_zone}
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
            "isActive": calendar.is_active,
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
