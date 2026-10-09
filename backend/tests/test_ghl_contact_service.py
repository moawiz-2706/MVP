from datetime import UTC, datetime

from app.models.entities import GHLCustomFieldMapping
from app.services.ghl_contact_service import GHLContactService


def test_custom_field_payload_uses_highlevel_id_key_and_field_value():
    mappings = [
        GHLCustomFieldMapping(
            ghl_field_id="field-waiver",
            passport_key="passport_waiver_url",
            object_type="contact",
            data_type="url",
        ),
        GHLCustomFieldMapping(
            ghl_field_id="field-start",
            passport_key="passport_start_at",
            object_type="contact",
            data_type="date_time",
        ),
        GHLCustomFieldMapping(
            ghl_field_id=None,
            passport_key="passport_signature_png",
            object_type="contact",
            data_type="text",
        ),
    ]

    payload = GHLContactService._custom_field_payload(
        {
            "passport_waiver_url": "https://passport.example/waiver/token",
            "passport_start_at": datetime(2026, 10, 8, 12, 30, tzinfo=UTC),
            "passport_signature_png": "must-not-be-sent",
        },
        mappings,
    )

    assert payload == [
        {
            "id": "field-waiver",
            "key": "passport_waiver_url",
            "fieldValue": "https://passport.example/waiver/token",
        },
        {
            "id": "field-start",
            "key": "passport_start_at",
            "fieldValue": "2026-10-08T12:30:00+00:00",
        },
    ]
