from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import PublicRateLimitBucket


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    value = forwarded.split(",", 1)[0].strip()
    return value or (request.client.host if request.client else "unknown")


def enforce_public_rate_limit(
    request: Request, db: Session, settings: Settings, *, scope: str
) -> None:
    now = datetime.now(UTC)
    key = f"{scope}:{client_ip(request)}"
    statement = insert(PublicRateLimitBucket).values(
        bucket_key=key,
        window_start=now,
        request_count=1,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[PublicRateLimitBucket.bucket_key],
        set_={
            "window_start": now,
            "request_count": 1,
        },
        where=PublicRateLimitBucket.window_start <= now - timedelta(minutes=1),
    ).returning(PublicRateLimitBucket.request_count)
    count = db.scalar(statement)
    if count is None:
        count = db.scalar(
            select(PublicRateLimitBucket.request_count).where(
                PublicRateLimitBucket.bucket_key == key
            )
        )
    db.commit()
    if count is not None and count > settings.public_rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="Too many public requests; try again shortly")
