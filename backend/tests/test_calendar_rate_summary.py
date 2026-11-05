import uuid
from types import SimpleNamespace

from app.schemas.configuration import CalendarRead
from app.services.configuration_service import ConfigurationService


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.queries = 0

    def execute(self, _statement):
        self.queries += 1
        return _Rows(self.rows)


def _service(rows):
    service = ConfigurationService.__new__(ConfigurationService)
    service.db = _FakeDB(rows)
    service.operator_id = uuid.uuid4()
    return service


def test_rate_summary_uses_one_query_and_lowest_active_price():
    multi, single, none = (SimpleNamespace(id=uuid.uuid4()) for _ in range(3))
    service = _service([
        (multi.id, 5900, "Adult"),
        (multi.id, 3500, "Child"),
        (single.id, 160000, "Private charter"),
    ])

    service._attach_rate_summaries([multi, single, none])

    assert service.db.queries == 1
    assert (multi.lowest_rate_minor, multi.active_rate_count, multi.single_rate_name) == (3500, 2, None)
    assert (single.lowest_rate_minor, single.active_rate_count, single.single_rate_name) == (160000, 1, "Private charter")
    assert (none.lowest_rate_minor, none.active_rate_count, none.single_rate_name) == (None, 0, None)


def test_empty_calendar_list_skips_the_query():
    service = _service([])
    service._attach_rate_summaries([])
    assert service.db.queries == 0


def test_calendar_read_defaults_keep_single_calendar_responses_valid():
    fields = CalendarRead.model_fields
    assert fields["lowest_rate_minor"].default is None
    assert fields["active_rate_count"].default == 0
    assert fields["single_rate_name"].default is None
