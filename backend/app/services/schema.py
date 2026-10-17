"""Programmatic Alembic access (used by `dataforce db upgrade` and the test fixtures)."""

from __future__ import annotations

from alembic.command import downgrade as alembic_downgrade
from alembic.command import upgrade as alembic_upgrade
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, pool

from app.config import BACKEND_DIR, get_settings


def alembic_config(url: str | None = None) -> Config:
    """Alembic config pointing at backend/alembic. `url=None` means settings.database_url
    (resolved by alembic/env.py). Logging setup is left to the caller."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    if url:
        cfg.attributes["db_url"] = url
    return cfg


def upgrade(url: str | None = None, revision: str = "head") -> None:
    alembic_upgrade(alembic_config(url), revision)


def downgrade(url: str | None = None, revision: str = "base") -> None:
    alembic_downgrade(alembic_config(url), revision)


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(url: str | None = None) -> str | None:
    """Revision the database is at (None = never migrated)."""
    resolved = url or get_settings().database_url.get_secret_value()
    engine = create_engine(resolved, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
