import os
import uuid
from datetime import UTC, datetime, time

import pytest

from app.models.entities import Calendar, CalendarHour, Operator
from app.schemas.fareharbor_replica import (
    BookingPolicyWrite,
    CustomFieldDefinitionWrite,
    MigrationImportCreate,
    ReconciliationRunCreate,
)
from app.services.fareharbor_replica_service import FareHarborReplicaService

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run replica tests",
)


def setup_operator(db):
    operator = Operator(
        ghl_location_id=f"loc-{uuid.uuid4().hex}",
        name="Replica Operator",
        slug=f"replica-{uuid.uuid4().hex[:8]}",
        time_zone="America/New_York",
    )
    db.add(operator)
    db.flush()
    calendar = Calendar(
        operator_id=operator.id,
        name="Swamp Tour",
        slug=f"swamp-{uuid.uuid4().hex[:8]}",
        duration_minutes=120,
        slot_interval_minutes=30,
        base_price_minor=5000,
    )
    db.add(calendar)
    db.flush()
    db.add(CalendarHour(calendar_id=calendar.id, day_of_week=4, start_time=time(8), end_time=time(18)))
    db.commit()
    return operator, calendar


def test_policy_versions_and_customer_deduplication(db):
    operator, calendar = setup_operator(db)
    service = FareHarborReplicaService(db, operator.id)
    first = service.replace_policy(
        calendar.id,
        BookingPolicyWrite(cancellation_cutoff_minutes=1440, requires_waiver=True),
    )
    second = service.replace_policy(
        calendar.id,
        BookingPolicyWrite(cancellation_cutoff_minutes=720, weather_refund_mode="manual_review"),
    )
    assert first["version"] == 1
    assert second["version"] == 2
    assert service.policy(calendar.id)["cancellation_cutoff_minutes"] == 720
    first_customer = service.upsert_customer("Ada", "Lovelace", "Ada@Example.com", "+1 (555) 010-0100")
    second_customer = service.upsert_customer("Ada", "Lovelace", "ada@example.com", "+15550100100")
    assert first_customer.id == second_customer.id
    db.commit()


def test_custom_field_and_migration_validation(db):
    operator, calendar = setup_operator(db)
    service = FareHarborReplicaService(db, operator.id)
    field = service.create_custom_field(
        CustomFieldDefinitionWrite(
            calendar_id=calendar.id,
            key="launch_site",
            label="Launch site",
            field_type="select",
            required=True,
            options=["North", "South"],
        )
    )
    assert field["key"] == "launch_site"
    staged = service.stage_import(MigrationImportCreate(rows=[{"external_id": "fh-1"}, {}]))
    assert staged["status"] == "needs_review"
    assert staged["blocking_errors"] == 1
    recon = service.reconciliation(ReconciliationRunCreate(scope="bookings"))
    assert recon["status"] == "completed"
    assert uuid.UUID(str(recon["id"]))
