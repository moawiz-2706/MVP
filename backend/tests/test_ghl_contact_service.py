import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.entities import GHLCustomFieldMapping
from app.services.ghl_contact_service import GHLContactService
from app.services.ghl_field_registry import contact_field_ids, object_field_keys


class FieldsClient:
    def __init__(self, fields=None, error=None):
        self.fields, self.error, self.calls = fields or [], error, []

    def request(self, method, path, *, version="", params=None, json=None):
        self.calls.append((method, path, params))
        if self.error:
            raise self.error
        return {"customFields": self.fields}


def _db(rows):
    db = MagicMock()
    db.scalars.return_value = rows
    return db


def test_contact_fields_are_found_by_key_without_manual_mapping():
    client = FieldsClient([
        {"id": "f-ref", "name": "Passport Booking Reference", "fieldKey": "contact.passport_booking_reference"},
        {"id": "f-waiver", "name": "Passport Waiver URL", "fieldKey": "contact.passport_waiver_url"},
        {"id": "f-other", "name": "Shoe size", "fieldKey": "contact.shoe_size"},
    ])
    db = _db([])
    ids = contact_field_ids(db, client, uuid.uuid4(), "loc-1", {"passport_booking_reference", "passport_waiver_url", "passport_total"})
    assert ids == {"passport_booking_reference": "f-ref", "passport_waiver_url": "f-waiver"}
    assert client.calls == [("GET", "/locations/loc-1/customFields", {"model": "contact"})]
    assert db.add.call_count == 2  # cached for the next sync


def test_fresh_cache_is_used_and_a_failed_lookup_keeps_it():
    row = GHLCustomFieldMapping(passport_key="passport_total", ghl_field_id="f-total", object_type="contact",
                                data_type="text", enabled=True, last_verified_at=datetime.now(UTC))
    client = FieldsClient()
    assert contact_field_ids(_db([row]), client, uuid.uuid4(), "loc-1", {"passport_total"}) == {"passport_total": "f-total"}
    assert client.calls == []
    row.last_verified_at = datetime.now(UTC) - timedelta(hours=2)
    failing = FieldsClient(error=RuntimeError("missing scope"))
    assert contact_field_ids(_db([row]), failing, uuid.uuid4(), "loc-1", {"passport_total"}) == {"passport_total": "f-total"}


def test_object_field_keys_accept_either_key_prefix():
    client = MagicMock()
    client.request.return_value = {"fields": [
        {"fieldKey": "custom_objects.passport_bookings.customer_email"},
        {"fieldKey": "custom_object.passport_bookings.waiver_link"},
    ]}
    assert object_field_keys(client, "custom_objects.passport_bookings", "loc-1") == {"customer_email", "waiver_link"}
    assert client.request.call_args.kwargs["version"] == "v3"
    client.request.side_effect = RuntimeError("403")
    assert object_field_keys(client, "custom_objects.passport_bookings", "loc-1") is None


def test_contact_upsert_sends_field_values_and_date_of_birth():
    service = GHLContactService.__new__(GHLContactService)
    sent = []

    def request(method, path, **kwargs):
        sent.append((method, path, kwargs.get("json")))
        if method == "GET":
            return {"contact": {"email": "pat@example.com"}}
        return {"contact": {"id": "c-1"}}

    service.client = SimpleNamespace(request=request)
    service._find_clear_match = lambda *args, **kwargs: None
    contact_id = service._upsert(
        "loc-1", existing_id="c-1", first_name="Pat", last_name="Guest", email="pat@example.com", phone=None,
        custom_fields=[{"id": "f-ref", "key": "passport_booking_reference", "fieldValue": "RM-1"}],
        date_of_birth=date(1990, 9, 25),
    )
    body = sent[-1][2]
    assert contact_id == "c-1"
    assert body["customFields"] == [{"id": "f-ref", "key": "passport_booking_reference", "fieldValue": "RM-1"}]
    assert body["dateOfBirth"] == "1990-09-25"
