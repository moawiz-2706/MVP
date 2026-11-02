"""A misconfigured deployment must stay diagnosable and fail closed.

Each case runs in a fresh interpreter because settings are read at import.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

PROBE = """
import json
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    out = {path: [r.status_code, r.json()] for path, r in (
        ("/api/health", client.get("/api/health")),
        ("/api/readiness", client.get("/api/readiness")),
        ("/api/v1/pwa/bootstrap", client.get("/api/v1/pwa/bootstrap")),
    )}
print(json.dumps(out))
"""


def _probe(**env: str) -> dict:
    clean = {key: value for key, value in os.environ.items() if not key.startswith(("GHL_", "STRIPE_", "APP_", "CRON_", "PWA_", "API_URL", "FRONTEND_URL", "DATABASE_URL", "ENVIRONMENT", "VERCEL_ENV"))}
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=BACKEND,
        env={**clean, **env},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_production_with_missing_settings_stays_up_and_locks_the_api():
    out = _probe(ENVIRONMENT="production", STRIPE_SECRET_KEY="sk_test_secret_value")
    assert out["/api/health"][0] == 200
    status, body = out["/api/readiness"]
    assert status == 503 and "GHL_CLIENT_ID" in body["detail"]
    assert "sk_test_secret_value" not in json.dumps(out)
    assert out["/api/v1/pwa/bootstrap"][0] == 503


def test_invalid_setting_value_is_named_without_its_value():
    out = _probe(PWA_SESSION_MINUTES="5")
    assert out["/api/health"][0] == 200
    status, body = out["/api/readiness"]
    assert status == 503 and body["detail"] == "Invalid settings: PWA_SESSION_MINUTES"
    assert out["/api/v1/pwa/bootstrap"][0] == 503


def test_development_defaults_are_unaffected():
    out = _probe()
    assert out["/api/readiness"][0] == 200
    assert out["/api/v1/pwa/bootstrap"][0] == 401  # normal auth, not the lock
