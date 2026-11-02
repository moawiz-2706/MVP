import inspect

from app.api.v1.ghl_oauth import oauth_callback
from app.core.config import Settings
from app.main import readiness


def test_oauth_callback_requires_state_query_parameter() -> None:
    parameter = inspect.signature(oauth_callback).parameters["state"]
    assert parameter.default is inspect.Parameter.empty


def test_production_defaults_reject_local_database_and_urls() -> None:
    settings = Settings(environment="production")
    try:
        settings.validate_runtime()
    except RuntimeError as exc:
        message = str(exc)
        assert "DATABASE_URL(non-localhost)" in message
        assert "API_URL" in message
        assert "FRONTEND_URL" in message
        assert "STRIPE_PUBLISHABLE_KEY" in message
    else:
        raise AssertionError("production defaults must not pass runtime validation")


def test_readiness_is_available_in_development() -> None:
    response = readiness()
    assert response.status_code == 200
    assert response.body == (
        b'{"status":"ready","schema_version":"development","environment":"non-production"}'
    )


def test_cookies_are_secure_for_any_https_or_production_deployment() -> None:
    assert not Settings(frontend_url="http://localhost:5173", api_url="").secure_cookies
    assert Settings(environment="production").secure_cookies
    assert Settings(vercel_env="production").secure_cookies
    assert Settings(frontend_url="https://passport.example.com").secure_cookies
    assert Settings(api_url="https://api.example.com").secure_cookies


def test_vercel_production_without_production_environment_is_flagged() -> None:
    assert Settings(vercel_env="production").environment_warnings
    assert not Settings(vercel_env="production", environment="production").environment_warnings
    assert not Settings(vercel_env="preview").environment_warnings


def test_rls_migration_enables_every_public_table() -> None:
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[2]
        / "supabase"
        / "migrations"
        / "041_enable_row_level_security.sql"
    ).read_text()
    assert "FROM pg_tables WHERE schemaname = 'public'" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "'041_enable_row_level_security'" in sql
    assert "CREATE POLICY" not in sql


def test_process_outbox_expires_holds_before_draining(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.api.v1 import internal_jobs

    calls: list[str] = []

    class FakeLifecycle:
        def __init__(self, db):
            pass

        def expire_pending_holds(self):
            calls.append("expire")
            return {"expired_holds": 2, "cancelled_bookings": 2, "skipped_paid": 0}

    class FakeOutbox:
        def __init__(self, db, settings):
            pass

        def process(self, limit):
            calls.append("drain")
            return {"processed": 3}

    monkeypatch.setattr(internal_jobs, "ReservationLifecycleService", FakeLifecycle)
    monkeypatch.setattr(internal_jobs, "OutboxService", FakeOutbox)
    result = internal_jobs.process_outbox(
        db=None, settings=SimpleNamespace(cron_secret="s3cret"), authorization="Bearer s3cret"
    )
    assert calls == ["expire", "drain"]
    assert result == {"expired_holds": 2, "cancelled_bookings": 2, "skipped_paid": 0, "processed": 3}
