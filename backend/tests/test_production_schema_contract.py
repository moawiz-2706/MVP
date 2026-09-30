from pathlib import Path

from app.models.entities import MessageTemplate, PublicAccessCredential, Staff, OutboxJob


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "012_staff_ghl_users.sql"
CUSTOM_ROLE_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "013_staff_custom_roles.sql"
AVAILABILITY_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "014_staff_ghl_availability.sql"
TIMEZONE_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "016_normalize_operator_time_zones.sql"
MESSAGE_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "030_message_templates.sql"
STAFF_LINK_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "032_private_staff_booking_links.sql"
STAFF_LINK_FIX_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "033_fix_staff_booking_purpose_constraint.sql"


def test_staff_user_migration_contains_model_columns_and_job_type() -> None:
    sql = MIGRATION.read_text()
    for column in (
        "ghl_user_id",
        "ghl_user_sync_status",
        "ghl_user_last_error",
        "ghl_permissions_verified_at",
    ):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in sql
    assert "'ghl_sync_staff_user'" in sql
    assert "ghl_user_id" in Staff.__table__.columns
    assert "ghl_sync_staff_user" in str(OutboxJob.__table_args__[1].sqltext)


def test_custom_role_migration_contains_passport_role_column() -> None:
    sql = CUSTOM_ROLE_MIGRATION.read_text()
    assert "ADD COLUMN IF NOT EXISTS custom_role text" in sql
    assert "custom_role" in Staff.__table__.columns


def test_availability_migration_contains_ghl_sync_columns() -> None:
    sql = AVAILABILITY_MIGRATION.read_text()
    for column in (
        "availability_time_zone",
        "availability_sync_status",
        "availability_last_error",
        "availability_last_synced_at",
    ):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in sql
        assert column in Staff.__table__.columns


def test_timezone_migration_repairs_blank_operator_values() -> None:
    sql = TIMEZONE_MIGRATION.read_text()
    assert "SET time_zone = 'UTC'" in sql
    assert "btrim(time_zone) <> ''" in sql


def test_message_template_migration_and_model_are_aligned() -> None:
    sql = MESSAGE_MIGRATION.read_text()
    assert "CREATE TABLE IF NOT EXISTS message_templates" in sql
    assert "030_message_templates" in sql
    assert "'ghl_booking_cancellation_email'" in sql
    assert "'ghl_booking_weather_email'" in sql
    assert "'ghl_booking_reschedule_email'" in sql
    assert MessageTemplate.__tablename__ == "message_templates"
    assert "event_type" in MessageTemplate.__table__.columns


def test_private_staff_booking_link_migration_and_model_are_aligned() -> None:
    sql = STAFF_LINK_MIGRATION.read_text()
    assert "staff_id uuid REFERENCES staff(id)" in sql
    assert "'staff_booking'" in sql
    assert "032_private_staff_booking_links" in sql
    assert "staff_id" in PublicAccessCredential.__table__.columns
    assert "staff_booking" in str(PublicAccessCredential.__table_args__[1].sqltext)


def test_private_staff_booking_constraint_fix_covers_legacy_migration() -> None:
    sql = STAFF_LINK_FIX_MIGRATION.read_text()
    assert "public_access_credentials_purpose_check" in sql
    assert "public_access_purpose_valid" in sql
    assert "033_fix_staff_booking_purpose_constraint" in sql
