from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

REQUIRED_PRODUCTION_TABLES = (
    "operators",
    "calendars",
    "bookings",
    "payments",
    "outbox_jobs",
    "ghl_oauth_states",
    "booking_adjustments",
    "calendar_booking_policies",
    "message_templates",
)
REQUIRED_SCHEMA_VERSION = "031_team_invoice_bookings"


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Build lazily so health checks do not require a database driver connection.

    Deployment target is Supabase's session pooler (Supavisor) behind a
    serverless backend. The engine is created once per warm instance (this
    factory is cached) and holds at most ONE pooled connection for that
    instance: pool_size=1 and no overflow connections. Concurrent requests in
    the same instance queue for the single connection rather than opening more.
    GHL token refreshes reuse the caller's existing SQLAlchemy session, so token
    refresh no longer needs a second connection.

    Notes:
    - pool_pre_ping recovers from connections the pooler has dropped while idle;
      pool_recycle proactively retires them before the pooler does.
    - prepare_threshold=None disables psycopg server-side prepared statements.
      Session-mode pooling tolerates them, but disabling keeps the app correct
      if DATABASE_URL is ever pointed at the transaction pooler (port 6543),
      where cached prepared statements break across pooled transactions.
    """
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_pre_ping=True,
        pool_recycle=settings.db_pool_recycle_seconds,
        connect_args={"connect_timeout": 10, "prepare_threshold": None},
    )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with get_session_factory()() as session:
        yield session


def check_database_readiness() -> dict[str, object]:
    """Verify connectivity, required tables, and the release marker migration."""
    with get_session_factory()() as session:
        session.execute(text("SELECT 1"))
        rows = session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = ANY(:tables)"
            ),
            {"tables": list(REQUIRED_PRODUCTION_TABLES)},
        )
        present = {row[0] for row in rows}
        missing = [table for table in REQUIRED_PRODUCTION_TABLES if table not in present]
        version = session.scalar(
            text(
                "SELECT version FROM passport_schema_version "
                "WHERE version = :version"
            ),
            {"version": REQUIRED_SCHEMA_VERSION},
        )
        if missing or version is None:
            parts = []
            if missing:
                parts.append("missing tables: " + ", ".join(missing))
            if version is None:
                parts.append(f"missing schema marker: {REQUIRED_SCHEMA_VERSION}")
            raise RuntimeError("Database is not ready: " + "; ".join(parts))
    return {"status": "ready", "schema_version": REQUIRED_SCHEMA_VERSION}
