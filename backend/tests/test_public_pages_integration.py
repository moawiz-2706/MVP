"""DB-backed tests for the public booking catalog, category pages, and category
slug uniqueness. Gated on TEST_DATABASE_URL (see conftest)."""

import os
import uuid

import pytest

from app.api.v1.public import public_catalog, public_category
from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import Calendar, CalendarCategory, Operator
from app.schemas.configuration import CategoryCreate
from app.services.configuration_service import ConfigurationService

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)


def _operator(db, *, public=True, active=True) -> Operator:
    op = Operator(
        ghl_location_id=f"loc-{uuid.uuid4()}",
        name="Punta Gorda Rentals",
        slug=f"op-{uuid.uuid4().hex[:8]}",
        time_zone="America/New_York",
        is_active=active,
        public_booking_enabled=public,
    )
    db.add(op)
    db.flush()
    return op


def _category(db, op, *, slug="kayak-rentals", active=True, deleted=False) -> CalendarCategory:
    cat = CalendarCategory(
        operator_id=op.id,
        name="Kayak Rentals",
        slug=slug,
        is_active=active,
        deleted_at=None,
    )
    if deleted:
        from datetime import UTC, datetime

        cat.deleted_at = datetime.now(UTC)
    db.add(cat)
    db.flush()
    return cat


def _calendar(db, op, cat, *, slug=None, active=True, public=True, deleted=False) -> Calendar:
    from datetime import UTC, datetime

    cal = Calendar(
        operator_id=op.id,
        calendar_category_id=cat.id if cat else None,
        name="3-Hour Single Kayak Rental",
        slug=slug or f"cal-{uuid.uuid4().hex[:8]}",
        duration_minutes=180,
        base_price_minor=7000,
        is_active=active,
        public_booking_enabled=public,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    db.add(cal)
    db.flush()
    return cal


def test_operator_catalog_includes_category_slug(db) -> None:
    op = _operator(db)
    cat = _category(db, op, slug="kayak-rentals")
    _calendar(db, op, cat)
    db.commit()
    result = public_catalog(op.slug, db)
    assert len(result.calendars) == 1
    assert result.calendars[0].category_slug == "kayak-rentals"


def test_category_page_lists_active_public_calendars(db) -> None:
    op = _operator(db)
    cat = _category(db, op, slug="kayak-rentals")
    _calendar(db, op, cat, slug="two-hour")
    _calendar(db, op, cat, slug="three-hour")
    _calendar(db, op, cat, slug="hidden", public=False)  # excluded
    db.commit()
    result = public_category(op.slug, "kayak-rentals", db)
    assert result.category_slug == "kayak-rentals"
    slugs = {c.slug for c in result.calendars}
    assert slugs == {"two-hour", "three-hour"}


def test_category_page_404_when_no_bookable_calendar(db) -> None:
    op = _operator(db)
    _category(db, op, slug="empty")
    db.commit()
    with pytest.raises(NotFoundError):
        public_category(op.slug, "empty", db)


def test_category_page_404_when_category_deleted(db) -> None:
    op = _operator(db)
    cat = _category(db, op, slug="gone", deleted=True)
    _calendar(db, op, cat)
    db.commit()
    with pytest.raises(NotFoundError):
        public_category(op.slug, "gone", db)


def test_category_page_404_when_operator_not_public(db) -> None:
    op = _operator(db, public=False)
    cat = _category(db, op, slug="kayak-rentals")
    _calendar(db, op, cat)
    db.commit()
    with pytest.raises(NotFoundError):
        public_category(op.slug, "kayak-rentals", db)


def test_duplicate_category_slug_rejected(db) -> None:
    op = _operator(db)
    db.commit()
    service = ConfigurationService(db, op.id)
    service.create_category(CategoryCreate(name="Kayak Rentals", slug="kayak-rentals"))
    with pytest.raises(ConflictError):
        service.create_category(CategoryCreate(name="Kayak Tours", slug="kayak-rentals"))


def test_same_slug_allowed_after_soft_delete(db) -> None:
    op = _operator(db)
    db.commit()
    service = ConfigurationService(db, op.id)
    first = service.create_category(CategoryCreate(name="Kayak Rentals", slug="kayak-rentals"))
    service.delete_category(first.id)
    # The partial-unique index frees the slug once the category is soft-deleted.
    reused = service.create_category(CategoryCreate(name="Kayak Rentals", slug="kayak-rentals"))
    assert reused.slug == "kayak-rentals"
