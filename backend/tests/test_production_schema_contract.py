from pathlib import Path

from app.models.entities import Staff, OutboxJob


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = REPOSITORY_ROOT / "supabase" / "migrations" / "012_staff_ghl_users.sql"


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
