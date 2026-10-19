from pathlib import Path

from app.models.entities import (
    Booking,
    BookingWaiver,
    GHLCustomFieldMapping,
    GHLSyncAttempt,
    GHLSyncRun,
    MessageTemplate,
    OutboxJob,
    PWAAuthHandoff,
    PublicAccessCredential,
    Staff,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "012_staff_ghl_users.sql"
CUSTOM_ROLE_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "013_staff_custom_roles.sql"
AVAILABILITY_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "014_staff_ghl_availability.sql"
TIMEZONE_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "016_normalize_operator_time_zones.sql"
MESSAGE_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "030_message_templates.sql"
STAFF_LINK_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "032_private_staff_booking_links.sql"
STAFF_LINK_FIX_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "033_fix_staff_booking_purpose_constraint.sql"
STAFF_TARGET_FIX_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "034_fix_staff_booking_target_constraint.sql"
WAIVER_RECONCILIATION_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "035_schema_reconciliation.sql"
GHL_SYNC_STATE_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "036_ghl_sync_state.sql"
PWA_AUTH_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "037_pwa_auth_handoffs.sql"
PWA_WORKSPACE_MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "038_pwa_workspace_performance.sql"


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


def test_private_staff_booking_target_constraint_fix_covers_staff_scope() -> None:
    sql = STAFF_TARGET_FIX_MIGRATION.read_text()
    assert "public_credentials_one_target" in sql
    assert "num_nonnulls(order_id, booking_id, staff_id) = 1" in sql
    assert "034_fix_staff_booking_target_constraint" in sql


def test_waiver_reconciliation_migration_and_model_are_aligned() -> None:
    sql = WAIVER_RECONCILIATION_MIGRATION.read_text()
    assert "ADD COLUMN IF NOT EXISTS token_digest text" in sql
    assert "digest(token, 'sha256')" in sql
    assert "ALTER COLUMN token_digest SET NOT NULL" in sql
    assert "035_schema_reconciliation" in sql


def test_ghl_sync_state_migration_and_models_are_aligned() -> None:
    sql = GHL_SYNC_STATE_MIGRATION.read_text()
    for table in ("ghl_sync_runs", "ghl_sync_attempts", "ghl_custom_field_mappings"):
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in sql
    for model in (GHLSyncRun, GHLSyncAttempt, GHLCustomFieldMapping):
        assert model.__tablename__ in sql
    for column in (
        "last_attempt_at",
        "last_synced_at",
        "sync_attempt_count",
        "last_error_code",
        "last_http_status",
        "last_sync_trigger",
    ):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in sql
    assert "ghl_contact_sync_status" in sql
    assert "036_ghl_sync_state" in sql


def test_pwa_auth_handoff_migration_and_model_are_aligned() -> None:
    sql = PWA_AUTH_MIGRATION.read_text()
    assert "CREATE TABLE IF NOT EXISTS public.pwa_auth_handoffs" in sql
    assert "code_digest" in PWAAuthHandoff.__table__.columns
    assert "expires_at" in PWAAuthHandoff.__table__.columns
    assert "037_pwa_auth_handoffs" in sql


def test_pwa_workspace_performance_migration_is_aligned() -> None:
    sql = PWA_WORKSPACE_MIGRATION.read_text()
    for index in (
        "ix_bookings_operator_status_start",
        "ix_booking_waivers_operator_status_booking",
        "ix_staff_assignments_operator_calendar_interval",
    ):
        assert f"CREATE INDEX IF NOT EXISTS {index}" in sql
    assert "038_pwa_workspace_performance" in sql
    assert "ix_bookings_operator_status_start" in {index.name for index in Booking.__table__.indexes}
    assert "ix_booking_waivers_operator_status_booking" in {
        index.name for index in BookingWaiver.__table__.indexes
    }
