from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import GHLInstallation, GHLWebhookEvent, Operator


class GHLWebhookService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def verify_signature(self, raw_body: bytes, signature: str | None) -> None:
        if not signature or not self.settings.ghl_webhook_public_key:
            raise ValueError("HighLevel webhook verification is not configured")
        key_text = self.settings.ghl_webhook_public_key.strip()
        try:
            if key_text.startswith("-----BEGIN"):
                import cryptography.hazmat.primitives.serialization as serialization

                key = serialization.load_pem_public_key(key_text.encode())
            else:
                key = Ed25519PublicKey.from_public_bytes(base64.b64decode(key_text, validate=True))
            if not isinstance(key, Ed25519PublicKey):
                raise ValueError("HighLevel webhook key is not Ed25519")
            key.verify(base64.b64decode(signature, validate=True), raw_body)
        except (ValueError, InvalidSignature, TypeError) as exc:
            raise ValueError("Invalid HighLevel webhook signature") from exc

    def process(self, payload: dict[str, Any], raw_body: bytes) -> bool:
        event_type = str(payload.get("type") or payload.get("event") or "UNKNOWN").upper()
        event_id = str(payload.get("webhookId") or payload.get("id") or hashlib.sha256(raw_body).hexdigest())
        location_id = payload.get("locationId")
        digest = hashlib.sha256(raw_body).hexdigest()
        inserted = self.db.scalar(
            insert(GHLWebhookEvent)
            .values(
                provider_event_id=event_id,
                event_type=event_type,
                location_id=str(location_id) if location_id else None,
                payload_hash=digest,
                payload=payload,
                status="received",
            )
            .on_conflict_do_nothing(index_elements=[GHLWebhookEvent.provider_event_id])
            .returning(GHLWebhookEvent.id)
        )
        if inserted is None:
            self.db.rollback()
            return False
        if event_type not in {"INSTALL", "UNINSTALL"}:
            event_row = self.db.get(GHLWebhookEvent, inserted)
            if event_row:
                event_row.status = "ignored"
                event_row.processed_at = datetime.now(UTC)
                event_row.payload = {**payload, "processing_note": "Verified event type is not a lifecycle event handled by Passport"}
            self.db.commit()
            return False
        if not location_id:
            raise ValueError("HighLevel lifecycle event has no locationId")
        installation = self.db.scalar(
            select(GHLInstallation).where(GHLInstallation.location_id == str(location_id)).with_for_update()
        )
        event_row = self.db.get(GHLWebhookEvent, inserted)
        if installation is None:
            if event_row:
                event_row.status = "ignored"
                event_row.processed_at = datetime.now(UTC)
            self.db.commit()
            return False
        operator = self.db.get(Operator, installation.operator_id)
        if event_type == "UNINSTALL":
            installation.is_installed = False
            installation.lifecycle_status = "uninstalled"
            installation.uninstalled_at = datetime.now(UTC)
            installation.authz_version += 1
            installation.generation += 1
            if operator:
                operator.is_active = False
        else:
            installation.last_verified_at = datetime.now(UTC)
        if event_row:
            event_row.status = "processed"
            event_row.processed_at = datetime.now(UTC)
        self.db.commit()
        return True
