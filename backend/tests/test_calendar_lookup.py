"""An inactive calendar must stay editable; a deleted one must not."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import NotFoundError
from app.services.configuration_service import ConfigurationService


def _service(calendar):
    db = MagicMock()
    db.scalar.return_value = calendar
    return ConfigurationService(db, uuid.uuid4()), db


def test_inactive_calendar_can_be_loaded_for_editing():
    calendar = SimpleNamespace(id=uuid.uuid4(), is_active=False, deleted_at=None)
    service, db = _service(calendar)
    assert service.get_calendar(calendar.id) is calendar
    query = str(db.scalar.call_args.args[0].whereclause)
    assert "is_active" not in query


def test_deleted_calendar_is_not_found():
    service, _ = _service(SimpleNamespace(id=uuid.uuid4(), is_active=False, deleted_at=datetime.now(UTC)))
    with pytest.raises(NotFoundError):
        service.get_calendar(uuid.uuid4())


def test_active_only_lookup_still_filters():
    service, db = _service(SimpleNamespace(id=uuid.uuid4(), is_active=True, deleted_at=None))
    service.get_calendar(uuid.uuid4(), active=True)
    assert "is_active" in str(db.scalar.call_args.args[0].whereclause)
