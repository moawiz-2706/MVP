"""After a missing migration is applied, the API recovers without a redeploy."""

import app.main as main


def test_database_not_ready_clears_once_the_check_passes(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "startup_error", "Database is not ready: missing schema marker: 049")
    monkeypatch.setattr(main, "_database_not_ready", True)
    monkeypatch.setattr(main, "_last_database_check", 0.0)
    monkeypatch.setattr(main, "check_database_readiness", lambda: calls.append(1) or {"status": "ready"})
    main._recheck_database()
    assert main.startup_error is None and main._database_not_ready is False and calls == [1]


def test_recheck_is_throttled_and_keeps_failing_state(monkeypatch):
    monkeypatch.setattr(main, "startup_error", "Database is not ready")
    monkeypatch.setattr(main, "_database_not_ready", True)
    monkeypatch.setattr(main, "_last_database_check", 0.0)

    def still_missing():
        raise RuntimeError("Database is not ready: missing schema marker: 049")

    monkeypatch.setattr(main, "check_database_readiness", still_missing)
    main._recheck_database()
    assert "049" in main.startup_error and main._database_not_ready
    calls = []
    monkeypatch.setattr(main, "check_database_readiness", lambda: calls.append(1))
    main._recheck_database()  # within 30 s: not checked again
    assert calls == []


def test_settings_errors_are_not_rechecked(monkeypatch):
    monkeypatch.setattr(main, "startup_error", "Invalid settings: DATABASE_URL")
    monkeypatch.setattr(main, "_database_not_ready", False)
    monkeypatch.setattr(main, "check_database_readiness", lambda: (_ for _ in ()).throw(AssertionError("must not run")))
    main._recheck_database()
    assert main.startup_error == "Invalid settings: DATABASE_URL"
