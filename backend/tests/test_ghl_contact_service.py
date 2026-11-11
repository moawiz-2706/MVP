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


def _recording_service(current):
    service = GHLContactService.__new__(GHLContactService)
    sent = []

    def request(method, path, **kwargs):
        sent.append((method, path, kwargs.get("json")))
        if method == "GET":
            return {"contact": current}
        return {"contact": {"id": "c-1"}}

    service.client = SimpleNamespace(request=request)
    service._find_clear_match = lambda *args, **kwargs: None
    return service, sent


def test_existing_phone_and_birthday_are_never_replaced():
    service, sent = _recording_service(
        {"email": "pat@example.com", "phone": "+19415550100", "dateOfBirth": "1980-01-01"}
    )
    service._upsert(
        "loc-1", existing_id="c-1", first_name="Pat", last_name="Guest", email="pat@example.com",
        phone="+19415550199", date_of_birth=date(1990, 9, 25),
    )
    body = sent[-1][2]
    assert "phone" not in body and "dateOfBirth" not in body
    assert body["firstName"] == "Pat"


def test_missing_phone_and_birthday_are_filled_in():
    service, sent = _recording_service({"email": "pat@example.com"})
    service._upsert(
        "loc-1", existing_id="c-1", first_name="Pat", last_name="Guest", email="pat@example.com",
        phone="(941) 555-0199", date_of_birth=date(1990, 9, 25),
    )
    body = sent[-1][2]
    assert body["phone"] == "+19415550199"
    assert body["dateOfBirth"] == "1990-09-25"


def test_guest_contacts_only_fill_missing_names():
    service, sent = _recording_service({"email": "sam@example.com", "firstName": "Samuel"})
    service._upsert(
        "loc-1", existing_id="c-2", first_name="Sam", last_name="Guest", email="sam@example.com",
        phone=None, fill_missing_only=True,
    )
    body = sent[-1][2]
    assert "firstName" not in body
    assert body["lastName"] == "Guest"


def test_guests_get_their_own_contacts_but_not_the_lead_or_minors():
    service = GHLContactService.__new__(GHLContactService)
    calls, tags = [], []
    service._upsert = lambda location, **kw: calls.append(kw) or f"id-{kw['email']}"
    service._add_tags = lambda contact_id, values: tags.append((contact_id, values))
    lead = SimpleNamespace(id=1, email="lead@example.com", is_minor=False, first_name="L", last_name="X", phone=None, date_of_birth=None)
    adult = SimpleNamespace(id=2, email="amy@example.com", is_minor=False, first_name="Amy", last_name="Y", phone="+19415550101", date_of_birth=date(1991, 1, 1))
    minor = SimpleNamespace(id=3, email="kid@example.com", is_minor=True, first_name="K", last_name="Y", phone=None, date_of_birth=None)
    no_email = SimpleNamespace(id=4, email=None, is_minor=False, first_name="N", last_name="Y", phone=None, date_of_birth=None)
    service._sync_guests("loc-1", [lead, adult, minor, no_email], lead)
    assert [c["email"] for c in calls] == ["amy@example.com"]
    assert calls[0]["fill_missing_only"] is True
    assert tags == [("id-amy@example.com", ["passport-guest"])]


def test_one_failing_guest_does_not_stop_the_others():
    service = GHLContactService.__new__(GHLContactService)
    done = []

    def upsert(location, **kw):
        if kw["email"] == "bad@example.com":
            raise RuntimeError("boom")
        done.append(kw["email"])
        return "id"

    service._upsert = upsert
    service._add_tags = lambda *args: None
    people = [
        SimpleNamespace(id=i, email=e, is_minor=False, first_name="A", last_name="B", phone=None, date_of_birth=None)
        for i, e in enumerate(["bad@example.com", "ok@example.com"])
    ]
    service._sync_guests("loc-1", people, None)
    assert done == ["ok@example.com"]


def test_guest_list_names_everyone_active_in_the_party():
    from app.services.ghl_booking_facts import guest_list

    people = [
        SimpleNamespace(first_name="Amy", last_name="Lee", is_minor=False, email="amy@example.com", phone="+19415550101", status="active"),
        SimpleNamespace(first_name="Kid", last_name="Lee", is_minor=True, email=None, phone=None, status="active"),
        SimpleNamespace(first_name="Gone", last_name="X", is_minor=False, email=None, phone=None, status="cancelled"),
    ]
    assert guest_list(people) == "Amy Lee (adult) · amy@example.com · +19415550101\nKid Lee (minor)"


def test_guest_list_is_sent_to_the_record_and_the_contact():
    from app.services.ghl_booking_facts import contact_values, object_properties

    facts = SimpleNamespace(**{name: "" for name in (
        "booking_reference booking_id booking_status payment_status payment_method invoice_status customer_name "
        "customer_email customer_phone activity tour_start tour_start_utc tour_end_utc total_amount currency "
        "source_partner assigned_staff waiver_status waiver_link waiver_signed_at waiver_expires_at emergency_contact"
    ).split()}, guests=2, marketing_opt_in=False, guest_list="Amy Lee (adult)")
    assert object_properties(facts)["guest_list"] == "Amy Lee (adult)"
    assert contact_values(facts)["passport_guest_list"] == "Amy Lee (adult)"


def test_guest_contact_is_linked_to_the_booking_record(monkeypatch):
    from app.services import ghl_booking_record_service as records

    service = GHLContactService.__new__(GHLContactService)
    service.operator_id = uuid.uuid4()
    service.client = object()
    booking = SimpleNamespace(booking_order_id=uuid.uuid4())
    service.db = SimpleNamespace(get=lambda model, _id: booking, scalar=lambda _q: "rec-1")
    linked = []
    monkeypatch.setattr(
        "app.services.ghl_contact_service.get_settings", lambda: SimpleNamespace(ghl_booking_record_sync_enabled=True), raising=False
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(ghl_booking_record_sync_enabled=True))
    monkeypatch.setattr(records.GHLBookingRecordService, "__init__", lambda self, db, op, settings: None)
    monkeypatch.setattr(records.GHLBookingRecordService, "_link_contact", lambda self, loc, rec, contact: linked.append((loc, rec, contact)))
    service._link_guest_to_record("loc-1", SimpleNamespace(booking_id=uuid.uuid4()), "c-guest")
    assert linked == [("loc-1", "rec-1", "c-guest")]


def test_lead_copy_with_waiver_details_is_preferred():
    order = SimpleNamespace(customer_email="lead@example.com")
    bare = SimpleNamespace(email="lead@example.com", phone=None, date_of_birth=None)
    filled = SimpleNamespace(email="lead@example.com", phone="+19415550199", date_of_birth=date(1988, 3, 10))
    assert GHLContactService._lead(order, [bare, filled]) is filled
