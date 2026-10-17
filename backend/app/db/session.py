"""Engine and session plumbing (sync SQLAlchemy 2.0 + psycopg3).

Services never commit: the caller owns the transaction, normally through `session_scope()`.
The pgvector `Vector` type needs no psycopg adapter registration: it sends/reads the text form
'[0.1,0.2,...]', which M2 will check with a real 768-d round trip.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import UnboundExecutionError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, describe_database_target, get_settings

_engines: dict[str, Engine] = {}
_lock = threading.Lock()

# Supabase's transaction pooler (Supavisor / pgbouncer in transaction mode) listens here and
# cannot keep psycopg3's server-side prepared statements.
TRANSACTION_POOLER_PORT = 6543


def database_target(url: str | None = None) -> str:
    """`host:port/dbname` of `url` (default: settings.database_url), never the credentials.
    For CLI banners ("migrating localhost:5433/dataforce") and log lines."""
    return describe_database_target(url or get_settings().database_url.get_secret_value())


def connect_args_for(url: str, settings: Settings) -> dict[str, Any]:
    """libpq / psycopg connection arguments: a connect timeout so a dead network or a stalled
    pooler fails in seconds, and no prepared statements behind a transaction pooler."""
    args: dict[str, Any] = {"connect_timeout": settings.db_connect_timeout_s}
    behind_pooler = make_url(url).port == TRANSACTION_POOLER_PORT
    if settings.db_disable_prepared_statements or behind_pooler:
        args["prepare_threshold"] = None
    return args


def _install_transaction_timeouts(engine: Engine, settings: Settings) -> None:
    """Apply statement_timeout / lock_timeout to every transaction with SET LOCAL semantics
    (`set_config(..., true)`). Unlike a libpq `options=-c ...` startup parameter this also works
    behind a transaction pooler, and it never leaks to the next client of a pooled connection.
    Autocommit connections (VACUUM in tests, admin DDL) are not affected."""
    statement_ms, lock_ms = settings.db_statement_timeout_ms, settings.db_lock_timeout_ms
    if not statement_ms and not lock_ms:
        return

    @event.listens_for(engine, "begin")
    def _set_timeouts(conn: Connection) -> None:
        conn.exec_driver_sql(
            "SELECT set_config('statement_timeout', %s, true), "
            "set_config('lock_timeout', %s, true)",
            (str(statement_ms), str(lock_ms)),
        )


def get_engine(url: str | None = None) -> Engine:
    """One pooled engine per URL (default: settings.database_url). Cached for the process.

    Timeouts come from settings (db_connect_timeout_s, db_statement_timeout_ms,
    db_lock_timeout_ms); an engine created before a settings change keeps its old values."""
    settings = get_settings()
    resolved = url or settings.database_url.get_secret_value()
    with _lock:
        engine = _engines.get(resolved)
        if engine is None:
            # pre_ping: a laptop that slept (or a Supabase pooler) drops idle connections.
            engine = create_engine(
                resolved,
                pool_pre_ping=True,
                hide_parameters=True,  # SQL parameters hold note bodies and names (SR4-08)
                connect_args=connect_args_for(resolved, settings),
            )
            _install_transaction_timeouts(engine, settings)
            _engines[resolved] = engine
        return engine


def dispose_engines() -> None:
    """Close every cached engine (tests, or before forking)."""
    with _lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()


class _DefaultEngineSession(Session):
    """Session that falls back to the default engine when it was created without a bind, so the
    module-level `SessionLocal` can exist without opening a connection at import time."""

    def get_bind(self, mapper: Any = None, **kw: Any) -> Any:
        try:
            return super().get_bind(mapper, **kw)
        except UnboundExecutionError:
            return get_engine()


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: the pipeline reads ORM rows after the unit of work committed.
    return sessionmaker(bind=engine, expire_on_commit=False)


SessionLocal: sessionmaker[Session] = sessionmaker(
    class_=_DefaultEngineSession, expire_on_commit=False
)


@contextmanager
def session_scope(factory: sessionmaker[Session] | None = None) -> Iterator[Session]:
    """Commit on success, roll back on any error, always close."""
    session = (factory or SessionLocal)()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
