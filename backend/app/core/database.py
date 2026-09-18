from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


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
