"""Migrations mirror models.py, and every table is locked down (RLS)."""

from __future__ import annotations

import importlib.util

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text

from app.config import BACKEND_DIR
from app.db.models import Base
from app.services import schema

pytestmark = pytest.mark.integration


def test_database_is_at_head(engine: Engine):
    assert schema.current_revision(engine.url.render_as_string(hide_password=False)) == (
        schema.head_revision()
    )


def test_migrations_have_no_diff_with_models(engine: Engine):
    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn, opts={"compare_type": True, "compare_server_default": True}
        )
        assert compare_metadata(ctx, Base.metadata) == []


def test_every_model_table_has_rls_enabled(engine: Engine):
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT relname, relrowsecurity FROM pg_class c JOIN pg_namespace n "
                "ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r'"
            )
        ).all()
    rls = {name: on for name, on in rows}
    expected = set(Base.metadata.tables) | {"alembic_version"}
    assert expected <= set(rls), expected - set(rls)
    assert [t for t in expected if not rls[t]] == []


def test_lockdown_list_covers_every_model_table():
    path = BACKEND_DIR / "alembic" / "versions" / "0002_lockdown.py"
    spec = importlib.util.spec_from_file_location("lockdown", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert set(Base.metadata.tables) | {"alembic_version"} == set(module.TABLES)
