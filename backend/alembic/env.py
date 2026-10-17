"""Alembic environment.

URL resolution, first match wins:
  1. `alembic -x db_url=postgresql+psycopg://...`  (AVOID: the password is visible in `ps` and in
     your shell history; a warning is logged. Export DATABASE_URL instead.)
  2. `config.attributes["db_url"]` (used by tests and `tt db upgrade`)
  3. `get_settings().database_url` (DATABASE_URL env var / backend/.env)

Migrations connect with a connect timeout, a lock_timeout (never wait forever behind a busy
session) and a generous statement_timeout: building the HNSW index can legitimately take minutes.
"""

from __future__ import annotations

import logging
from logging.config import fileConfig

from sqlalchemy import create_engine, pool, text

from alembic import context
from app.config import get_settings
from app.db.models import Base

config = context.config
log = logging.getLogger("alembic.env")

# Programmatic callers (tests, the CLI) set this to keep their own logging untouched.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# Serializes concurrent `upgrade` runs (two shells, CI jobs) on the same database.
_MIGRATION_LOCK_ID = 7_461_220_001


def _database_url() -> str:
    from_x = context.get_x_argument(as_dictionary=True).get("db_url")
    if from_x:
        log.warning(
            "db_url was given with -x: its password is visible in the process list and your shell "
            "history. Prefer exporting DATABASE_URL."
        )
    return (
        from_x or config.attributes.get("db_url") or get_settings().database_url.get_secret_value()
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # NullPool: a short-lived engine for a short-lived process; nothing to keep warm.
    engine = create_engine(
        _database_url(),
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": get_settings().db_connect_timeout_s},
    )
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                compare_server_default=True,
            )
            with context.begin_transaction():
                if connection.dialect.name == "postgresql":
                    connection.execute(
                        text("SELECT pg_advisory_xact_lock(:id)"), {"id": _MIGRATION_LOCK_ID}
                    )
                    # SET LOCAL: scoped to the migration transaction (SR4-10).
                    connection.execute(text("SET LOCAL lock_timeout = '15s'"))
                    connection.execute(text("SET LOCAL statement_timeout = '5min'"))
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
