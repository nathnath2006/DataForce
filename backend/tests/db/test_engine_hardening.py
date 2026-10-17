"""SR3-10: connect timeout, per-transaction statement / lock timeouts, pooler handling."""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.config import Settings, get_settings
from app.db import session as db_session
from app.db.session import connect_args_for, database_target


def make(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


def test_connect_args_have_the_connect_timeout():
    args = connect_args_for("postgresql+psycopg://u:p@localhost:5433/db", make())
    assert args == {"connect_timeout": 10}
    args = connect_args_for(
        "postgresql+psycopg://u:p@localhost:5433/db", make(db_connect_timeout_s=3)
    )
    assert args["connect_timeout"] == 3


def test_prepared_statements_are_off_behind_the_transaction_pooler_or_on_request():
    pooler = "postgresql+psycopg://u:p@aws-0.pooler.supabase.com:6543/postgres?sslmode=require"
    direct = "postgresql+psycopg://u:p@db.x.supabase.co:5432/postgres?sslmode=require"
    assert connect_args_for(pooler, make())["prepare_threshold"] is None
    assert "prepare_threshold" not in connect_args_for(direct, make())
    forced = connect_args_for(direct, make(db_disable_prepared_statements=True))
    assert forced["prepare_threshold"] is None


def test_database_target_never_contains_credentials():
    assert database_target("postgresql+psycopg://user:s3cret-pw@db.example.org:6543/x") == (
        "db.example.org:6543/x"
    )


@pytest.fixture
def fresh_engine(monkeypatch, test_database_url):
    """A new engine on the test database (own cache key) built with overridden settings."""
    created: list[str] = []

    def build(**env: str):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        url = f"{test_database_url}?application_name=hardening_{uuid.uuid4().hex[:6]}"
        created.append(url)
        return db_session.get_engine(url)

    yield build
    for url in created:
        engine = db_session._engines.pop(url, None)
        if engine is not None:
            engine.dispose()
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.mark.integration
def test_every_transaction_gets_the_default_timeouts(engine):
    with engine.connect() as connection:
        assert connection.scalar(text("SHOW statement_timeout")) == "1min"
        assert connection.scalar(text("SHOW lock_timeout")) == "15s"
        connection.rollback()
    with engine.connect() as connection:  # the setting is per transaction, not sticky
        connection.rollback()
        assert connection.scalar(text("SHOW statement_timeout")) == "1min"


@pytest.mark.integration
def test_a_runaway_statement_is_cancelled(fresh_engine):
    engine = fresh_engine(DB_STATEMENT_TIMEOUT_MS="300")
    started = time.monotonic()
    with pytest.raises(OperationalError, match="statement timeout"), engine.connect() as conn:
        conn.execute(text("SELECT pg_sleep(5)"))
    assert time.monotonic() - started < 3


@pytest.mark.integration
def test_a_blocked_row_lock_gives_up_after_the_lock_timeout(fresh_engine):
    engine = fresh_engine(DB_LOCK_TIMEOUT_MS="300", DB_STATEMENT_TIMEOUT_MS="0")
    other = fresh_engine(DB_LOCK_TIMEOUT_MS="300", DB_STATEMENT_TIMEOUT_MS="0")
    with engine.connect() as holder, other.connect() as waiter:
        holder.execute(text("LOCK TABLE workspace IN ACCESS EXCLUSIVE MODE"))
        started = time.monotonic()
        with pytest.raises(OperationalError, match="lock timeout"):
            waiter.execute(text("SELECT count(*) FROM workspace"))
        assert time.monotonic() - started < 3
        holder.rollback()


@pytest.mark.integration
def test_timeouts_can_be_switched_off(fresh_engine):
    engine = fresh_engine(DB_STATEMENT_TIMEOUT_MS="0", DB_LOCK_TIMEOUT_MS="0")
    with engine.connect() as connection:
        assert connection.scalar(text("SHOW statement_timeout")) == "0"
        assert connection.scalar(text("SHOW lock_timeout")) == "0"
        connection.rollback()


def test_an_unreachable_host_fails_within_the_connect_timeout(monkeypatch):
    """TEST-NET-1 (RFC 5737) is not routed: the connection attempt must stop at the timeout."""
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_S", "1")
    get_settings.cache_clear()
    url = "postgresql+psycopg://u:p@192.0.2.1:5432/none?sslmode=require&application_name=ct"
    try:
        engine = db_session.get_engine(url)
        started = time.monotonic()
        with pytest.raises(OperationalError), engine.connect():
            pass
        assert time.monotonic() - started < 10
    finally:
        engine = db_session._engines.pop(url, None)
        if engine is not None:
            engine.dispose()
        monkeypatch.undo()
        get_settings.cache_clear()
