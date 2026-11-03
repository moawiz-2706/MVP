"""HighLevel "Passport Bookings" custom object records (no live HighLevel)."""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.services import ghl_booking_record_service as service_module
from app.services.ghl_booking_record_service import GHLBookingRecordService, enqueue_booking_record_sync
from app.services.ghl_client import GHLAPIError

KEY = "custom_objects.passport_bookings"
PROPS = {"booking_reference": "RM-1", "passport_booking_id": "x", "payment_status": "succeeded",
         "invoice_status": "", "waiver_status": "pending"}


class FakeClient:
    def __init__(self, *, association_first="contact", put_error=None, relation_error=None):
        self.calls = []
        self.association_first = association_first
        self.put_error = put_error
        self.relation_error = relation_error

    def request(self, method, path, *, version="", params=None, json=None):
        if path == f"/objects/{KEY}":
            return {"fields": [{"fieldKey": f"{KEY}.{name}"} for name in PROPS]}
        self.calls.append((method, path, params, json))
        if method == "PUT" and self.put_error:
            raise self.put_error
        if method == "POST" and path.endswith("/records"):
            return {"record": {"id": "rec-new"}}
        if path.startswith("/associations/objectKey/"):
            other = KEY if self.association_first == "contact" else "contact"
            return {"id": "assoc-1", "firstObjectKey": self.association_first, "secondObjectKey": other}
        if path == "/associations/relations" and self.relation_error:
            raise self.relation_error
        return {}


def _service(monkeypatch, client, mapping):
    order = SimpleNamespace(id=uuid.uuid4(), operator_id=uuid.uuid4(), ghl_contact_id="contact-1", public_reference="RM-1")
    db = MagicMock()
    db.scalar.side_effect = [order, mapping]
    db.get.return_value = SimpleNamespace(ghl_location_id="loc-1")
    monkeypatch.setattr(service_module, "record_properties", lambda db, order, keys=None: {k: v for k, v in PROPS.items() if keys is None or k in keys})
    service = GHLBookingRecordService.__new__(GHLBookingRecordService)
    service.db, service.operator_id, service.client = db, order.operator_id, client
    service.settings = Settings(ghl_booking_object_key=KEY)
    return service, order, db


def _mapping(**values):
    base = {"ghl_record_id": None, "ghl_contact_id": None, "contact_linked": False, "status": "pending",
            "last_error": None, "synced_at": None}
    return SimpleNamespace(**{**base, **values})


def test_first_sync_creates_the_record_and_links_the_contact(monkeypatch):
    client, mapping = FakeClient(), _mapping()
    service, order, _ = _service(monkeypatch, client, mapping)
    assert service.sync(order.id) == "rec-new"
    create = client.calls[0]
    assert create[:2] == ("POST", f"/objects/{KEY}/records")
    assert create[3] == {"locationId": "loc-1", "properties": PROPS}
    relation = client.calls[-1]
    assert relation[1] == "/associations/relations"
    assert relation[3] == {"locationId": "loc-1", "associationId": "assoc-1", "firstRecordId": "contact-1", "secondRecordId": "rec-new"}
    assert (mapping.ghl_record_id, mapping.contact_linked, mapping.status) == ("rec-new", True, "synced")


def test_record_side_first_association_puts_record_first(monkeypatch):
    client = FakeClient(association_first=KEY)
    service, order, _ = _service(monkeypatch, client, _mapping())
    service.sync(order.id)
    assert client.calls[-1][3]["firstRecordId"] == "rec-new"
    assert client.calls[-1][3]["secondRecordId"] == "contact-1"


def test_later_syncs_update_in_place_without_relinking(monkeypatch):
    client = FakeClient()
    mapping = _mapping(ghl_record_id="rec-1", ghl_contact_id="contact-1", contact_linked=True)
    service, order, _ = _service(monkeypatch, client, mapping)
    service.sync(order.id)
    assert client.calls == [("PUT", f"/objects/{KEY}/records/rec-1", {"locationId": "loc-1"}, {"properties": PROPS})]


def test_record_deleted_in_highlevel_is_recreated_and_relinked(monkeypatch):
    client = FakeClient(put_error=GHLAPIError("not found", status_code=404))
    mapping = _mapping(ghl_record_id="rec-gone", ghl_contact_id="contact-1", contact_linked=True)
    service, order, _ = _service(monkeypatch, client, mapping)
    assert service.sync(order.id) == "rec-new"
    assert [call[0] for call in client.calls] == ["PUT", "POST", "GET", "POST"]


def test_existing_link_is_not_an_error(monkeypatch):
    client = FakeClient(relation_error=GHLAPIError("Relation already exists", status_code=400))
    mapping = _mapping()
    service, order, _ = _service(monkeypatch, client, mapping)
    service.sync(order.id)
    assert mapping.status == "synced"


def test_failures_are_recorded_and_raised_for_retry(monkeypatch):
    client = FakeClient(put_error=GHLAPIError("scope", status_code=401, permanent=True))
    mapping = _mapping(ghl_record_id="rec-1", contact_linked=True, ghl_contact_id="contact-1")
    service, order, _ = _service(monkeypatch, client, mapping)
    with pytest.raises(GHLAPIError):
        service.sync(order.id)
    assert mapping.status == "failed" and "scope" in mapping.last_error


def test_queueing_is_off_by_default_and_never_breaks_a_booking():
    db = MagicMock()
    order = SimpleNamespace(id=uuid.uuid4(), operator_id=uuid.uuid4())
    enqueue_booking_record_sync(db, Settings(), order)
    assert not db.method_calls
    from sqlalchemy.exc import ProgrammingError

    db.execute.side_effect = ProgrammingError("INSERT", {}, Exception("missing job type"))
    enqueue_booking_record_sync(db, Settings(ghl_booking_record_sync_enabled=True), order)
    db.begin_nested.assert_called_once()
    db.commit.assert_not_called()


def test_migration_allows_the_job_and_creates_the_table():
    from pathlib import Path

    migration = (Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "048_ghl_booking_records.sql").read_text()
    assert "'ghl_sync_booking_record'" in migration
    assert "CREATE TABLE IF NOT EXISTS public.ghl_booking_records" in migration


def test_field_guide_lists_exactly_the_keys_passport_sends():
    import re
    from pathlib import Path

    from app.services.ghl_booking_facts import BASE_OBJECT_FIELDS, contact_values, object_properties

    guide = (Path(__file__).resolve().parents[2] / "docs" / "integrations" / "highlevel" / "CRM_FIELDS.md").read_text(encoding="utf-8")
    object_part, contact_part = guide.split("## Passport Bookings object")[1], guide.split("## Contact: custom fields")[1].split("## Passport Bookings object")[0]
    documented_object = set(re.findall(r"\| `([a-z_]+)` \|", object_part))
    documented_contact = set(re.findall(r"\| `([a-z_]+)` \|", contact_part))
    facts = SimpleNamespace(**{name: "" for name in (
        "booking_reference booking_id booking_status payment_status payment_method invoice_status customer_name "
        "customer_email customer_phone activity tour_start tour_start_utc tour_end_utc total_amount currency "
        "source_partner assigned_staff waiver_status waiver_link waiver_signed_at waiver_expires_at emergency_contact"
    ).split()}, guests=0, marketing_opt_in=False)
    assert documented_object == set(object_properties(facts))
    assert documented_contact == set(contact_values(facts))
    assert BASE_OBJECT_FIELDS <= documented_object
