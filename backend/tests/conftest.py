"""Shared fixtures.

Most of the suite is pure-logic and runs everywhere. The DB-dependent
scenarios in the specification's test matrix (availability engine end-to-end,
soft-delete cascades, and true `SELECT ... FOR UPDATE` concurrency) require a
real PostgreSQL instance: SQLite cannot honour `postgresql` column types or
row-level lock semantics, so faking them there would prove nothing.

Set ``TEST_DATABASE_URL`` to a disposable Postgres database, e.g.::

    TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/rental_test

to enable the integration tests. Without it they are skipped, not failed.
"""

import os

import pytest

import app.models.entities  # noqa: F401  (registers all tables on Base.metadata)
from app.models.base import Base

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

requires_db = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="Set TEST_DATABASE_URL to a disposable Postgres database to run DB integration tests",
)


@pytest.fixture()
def engine():
    from sqlalchemy import create_engine

    eng = create_engine(TEST_DATABASE_URL, future=True)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture()
def db(engine):
    from sqlalchemy.orm import sessionmaker

    maker = sessionmaker(engine, expire_on_commit=False, future=True)
    session = maker()
    try:
        yield session
    finally:
        session.close()


class FakeGHL:
    """Stands in for GHLClient in DB tests; records every request."""

    calls: list[tuple[str, str, dict | None]] = []

    def __init__(self, operator_id, db=None) -> None:
        self.operator_id = operator_id

    def request(self, method, path, *, version="", params=None, json=None):
        FakeGHL.calls.append((method, path, json))
        if path == "/contacts/lookup":
            return {"contacts": []}
        if method == "POST" and path == "/contacts/":
            return {"contact": {"id": f"contact-{len(FakeGHL.calls)}"}}
        if method == "PUT":
            return {"contact": {"id": path.split("/")[2]}}
        if path.endswith("/tags"):
            return {"tags": json["tags"]}
        if path == "/conversations/messages":
            return {"conversationId": "conv-1", "messageId": "msg-1"}
        return {}


@pytest.fixture
def ghl(monkeypatch):
    """Replace HighLevel with a recorder; returns the list of (method, path, body)."""
    from app.services import ghl_contact_service, ghl_email_service

    FakeGHL.calls = []
    monkeypatch.setattr(ghl_contact_service, "GHLClient", FakeGHL)
    monkeypatch.setattr(ghl_email_service, "GHLClient", FakeGHL)
    return FakeGHL.calls
