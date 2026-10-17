"""Shared test fixtures.

Database tests are marked `@pytest.mark.integration` and need Postgres + pgvector:
`docker compose up -d db` (port 5433, database `dataforce_test`). When it is unreachable they are
SKIPPED with a clear message instead of failing.

Safety: DATABASE_URL is pointed at the test database for the whole session, so no test (or code
under test falling back to `get_settings()`) can touch the dev database by accident. The test
URL itself is checked first (SR3-04): its database name must end with `_test`, differ from the
dev database name, and live on a loopback host (override only with ALLOW_REMOTE_TEST_DB=1). When
the check fails, DATABASE_URL is pointed at an unroutable placeholder and the session exits
before the first integration test, with the reason.

Isolation: `db_session` runs every test inside an outer transaction that is rolled back at the
end (SQLAlchemy 2.0 "join an external transaction" recipe), so tests may call `commit()` freely.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache

import pytest
from sqlalchemy import Connection, Engine, create_engine, pool, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import database_is_local, get_settings
from app.db.session import dispose_engines, get_engine
from app.services import schema

ALLOW_REMOTE_ENV = "ALLOW_REMOTE_TEST_DB"
# Never resolves to a real database: used as DATABASE_URL when the test URL was refused.
_UNROUTABLE_URL = "postgresql+psycopg://guard:guard@127.0.0.1:1/refused_test"


def check_test_database_url(
    test_url: str, dev_url: str | None = None, *, allow_remote: bool = False
) -> str | None:
    """None when `test_url` is safe to run destructive tests against, else the reason (never
    containing a password). Rules: the database name ends with `_test`; it differs from the
    dev database name (`dev_url`, the non-test DATABASE_URL); the host is loopback unless
    `allow_remote` (ALLOW_REMOTE_TEST_DB=1)."""
    try:
        test = make_url(test_url)
    except Exception:  # noqa: BLE001 - make_url's messages can quote the URL
        return "TEST_DATABASE_URL is not a valid database URL"
    name = test.database or ""
    if not name.endswith("_test"):
        return (
            f"refusing to run integration tests: the test database name {name!r} must end "
            "with '_test' (integration tests create, migrate and delete data)"
        )
    if dev_url:
        try:
            dev_name = make_url(dev_url).database
        except Exception:  # noqa: BLE001
            dev_name = None
        if dev_name is not None and dev_name == name:
            return (
                f"refusing to run integration tests: TEST_DATABASE_URL targets database "
                f"{name!r}, the same name as the dev DATABASE_URL"
            )
    if not allow_remote and not database_is_local(test):
        return (
            "refusing to run integration tests against a non-loopback host "
            f"(set {ALLOW_REMOTE_ENV}=1 if that is really intended)"
        )
    return None


# Must run before anything calls get_settings() for real, hence at import time. The dev URL is
# read first (DATABASE_URL env var / backend/.env / default), then replaced by the test URL.
_settings = get_settings()
TEST_DATABASE_URL = _settings.test_database_url.get_secret_value()
TEST_DB_PROBLEM = check_test_database_url(
    TEST_DATABASE_URL,
    _settings.database_url.get_secret_value(),
    allow_remote=os.environ.get(ALLOW_REMOTE_ENV) == "1",
)
os.environ["DATABASE_URL"] = _UNROUTABLE_URL if TEST_DB_PROBLEM else TEST_DATABASE_URL
del _settings
get_settings.cache_clear()


@lru_cache(maxsize=1)
def _unreachable_reason() -> str | None:
    """None when the test database accepts connections, else a short human-readable reason.
    (The URL is never echoed: it contains the password.)"""
    engine = create_engine(
        TEST_DATABASE_URL, poolclass=pool.NullPool, connect_args={"connect_timeout": 3}
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return None
    except Exception as exc:
        detail = str(getattr(exc, "orig", exc)).strip().splitlines()
        return detail[0] if detail else type(exc).__name__
    finally:
        engine.dispose()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Fail fast, before any test ran, when integration tests are selected against an unsafe
    database."""
    if TEST_DB_PROBLEM and any(i.get_closest_marker("integration") for i in items):
        pytest.exit(TEST_DB_PROBLEM, returncode=2)


def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker("integration") is None:
        return
    if TEST_DB_PROBLEM:  # safety net when collection hooks were bypassed
        pytest.exit(TEST_DB_PROBLEM, returncode=2)
    reason = _unreachable_reason()
    if reason is not None:
        pytest.skip(
            f"test database unreachable ({reason}). Start it with `docker compose up -d db` "
            "(database `dataforce_test` on localhost:5433, or set TEST_DATABASE_URL)."
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    dispose_engines()


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def engine(test_database_url: str) -> Engine:
    """Engine on the test database, migrated to head once per session."""
    schema.upgrade(test_database_url)
    return get_engine(test_database_url)


@pytest.fixture
def db_connection(engine: Engine) -> Iterator[Connection]:
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


@pytest.fixture
def db_session(db_connection: Connection) -> Iterator[Session]:
    """A session whose work is discarded at the end of the test."""
    session = Session(
        bind=db_connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def session_factory(db_connection: Connection) -> sessionmaker[Session]:
    """For code that opens its own sessions (e.g. DbUsageRecorder).

    Caveat: these sessions share `db_session`'s connection and outer transaction, so what they
    "commit" is visible to `db_session` but is still rolled back when the test ends. They are
    NOT independent transactions: a test that needs real isolation between two connections
    must build its own engine."""
    return sessionmaker(
        bind=db_connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )


@pytest.fixture
def ws_id(db_session: Session):
    """A fresh workspace (rolled back with the test)."""
    from app.services import workspaces

    return workspaces.create_workspace(db_session, "test-ws", "Test workspace").id
