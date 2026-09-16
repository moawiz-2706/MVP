from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.entities import PublicAccessCredential


class PublicAccessService:
    """Issue and verify purpose-bound public capabilities.

    The raw token is returned only to the caller that is creating a link. The
    database stores a digest, so a database read cannot be used as a bearer
    credential. Legacy URL tokens remain supported by their owning services
    during the migration window.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def issue(
        self,
        *,
        operator_id: uuid.UUID,
        purpose: str,
        order_id: uuid.UUID | None = None,
        booking_id: uuid.UUID | None = None,
        lifetime: timedelta,
    ) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        self.db.add(
            PublicAccessCredential(
                operator_id=operator_id,
                order_id=order_id,
                booking_id=booking_id,
                token_digest=self.digest(token),
                purpose=purpose,
                issued_at=now,
                expires_at=now + lifetime,
            )
        )
        return token

    def verify(
        self,
        token: str,
        *,
        purpose: str,
        order_id: uuid.UUID | None = None,
        booking_id: uuid.UUID | None = None,
        touch: bool = True,
    ) -> PublicAccessCredential:
        credential = self.db.scalar(
            select(PublicAccessCredential)
            .where(
                PublicAccessCredential.token_digest == self.digest(token),
                PublicAccessCredential.purpose == purpose,
                PublicAccessCredential.revoked_at.is_(None),
            )
            .with_for_update() if touch else select(PublicAccessCredential).where(
                PublicAccessCredential.token_digest == self.digest(token),
                PublicAccessCredential.purpose == purpose,
                PublicAccessCredential.revoked_at.is_(None),
            )
        )
        now = datetime.now(UTC)
        if (
            credential is None
            or credential.expires_at <= now
            or (order_id is not None and credential.order_id != order_id)
            or (booking_id is not None and credential.booking_id != booking_id)
        ):
            raise NotFoundError("Access link not found")
        if touch:
            credential.last_used_at = now
        return credential

    def revoke(self, *, order_id: uuid.UUID | None = None, booking_id: uuid.UUID | None = None) -> int:
        statement = select(PublicAccessCredential).where(
            PublicAccessCredential.revoked_at.is_(None)
        )
        if order_id is not None:
            statement = statement.where(PublicAccessCredential.order_id == order_id)
        if booking_id is not None:
            statement = statement.where(PublicAccessCredential.booking_id == booking_id)
        now = datetime.now(UTC)
        rows = list(self.db.scalars(statement))
        for row in rows:
            row.revoked_at = now
        return len(rows)
