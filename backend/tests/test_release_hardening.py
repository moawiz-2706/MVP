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
    assert response.body == b'{"status":"ready","schema_version":"development"}'
