"""Find the HighLevel fields an operator created, by key, so nobody maps ids by hand.

* Contact custom fields: `GET /locations/{id}/customFields?model=contact`.
  A field whose key ends in a Passport key (e.g. `contact.passport_payment_status`)
  is cached in `ghl_custom_field_mappings` and refreshed hourly.
* Custom object fields: `GET /objects/{key}?locationId=…&fetchProperties=true`.
  Only properties whose field exists are sent, so the record grows as fields
  are added in HighLevel and never fails on a field that was not created.

A lookup that fails (for example a missing scope) is logged and the caller
keeps what it already knows; it never blocks a booking sync.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import GHLCustomFieldMapping

logger = logging.getLogger("passport.ghl_fields")
REFRESH_AFTER = timedelta(hours=1)


def _short_key(field_key: str) -> str:
    return field_key.rsplit(".", 1)[-1].strip().lower()


def contact_field_ids(
    db: Session, client: Any, operator_id: uuid.UUID, location_id: str, wanted: set[str]
) -> dict[str, str]:
    """Passport key -> HighLevel contact custom field id, for fields that exist."""
    mappings = {
        row.passport_key: row
        for row in db.scalars(
            select(GHLCustomFieldMapping).where(
                GHLCustomFieldMapping.operator_id == operator_id,
                GHLCustomFieldMapping.object_type == "contact",
            )
        )
    }
    now = datetime.now(UTC)
    stale = not mappings or any(
        row.last_verified_at is None or row.last_verified_at < now - REFRESH_AFTER
        for row in mappings.values()
    )
    if stale:
        try:
            found = client.request(
                "GET",
                f"/locations/{location_id}/customFields",
                version="2021-07-28",
                params={"model": "contact"},
            )
            fields = found.get("customFields", []) if isinstance(found, dict) else []
            by_key = {
                _short_key(str(field.get("fieldKey") or "")): field
                for field in fields
                if isinstance(field, dict) and field.get("id") and field.get("fieldKey")
            }
            for key in wanted:
                field = by_key.get(key)
                row = mappings.get(key)
                if field is None:
                    if row is not None and row.ghl_field_id:
                        row.ghl_field_id = None  # deleted in HighLevel
                        row.last_verified_at = now
                    continue
                if row is None:
                    row = GHLCustomFieldMapping(
                        operator_id=operator_id, object_type="contact", passport_key=key, data_type="text"
                    )
                    db.add(row)
                    mappings[key] = row
                row.ghl_field_id = str(field["id"])
                row.ghl_field_name = str(field.get("name") or key)
                row.enabled = True
                row.last_error = None
                row.last_verified_at = now
            db.flush()
        except Exception:
            logger.exception("Could not read HighLevel contact custom fields; using cached ones")
    return {
        key: row.ghl_field_id
        for key, row in mappings.items()
        if key in wanted and row.enabled and row.ghl_field_id
    }


def object_field_keys(client: Any, object_key: str, location_id: str) -> set[str] | None:
    """Short keys of the custom object's fields, or None when they cannot be read."""
    try:
        found = client.request(
            "GET",
            f"/objects/{object_key}",
            version="v3",
            params={"locationId": location_id, "fetchProperties": "true"},
        )
    except Exception:
        logger.exception("Could not read the %s fields; sending the base fields only", object_key)
        return None
    fields = []
    if isinstance(found, dict):
        fields = found.get("fields") or (found.get("object") or {}).get("fields") or []
    keys = {
        _short_key(str(field.get("fieldKey") or field.get("key") or ""))
        for field in fields
        if isinstance(field, dict)
    }
    keys.discard("")
    return keys or None
