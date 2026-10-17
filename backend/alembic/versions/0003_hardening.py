"""Hardening from the SR4 review.

- SR4-01: BEFORE TRUNCATE guard on note / comment (also stops TRUNCATE ... CASCADE from parents).
- SR4-02: a version can be corrected at most once (partial unique index on corrects_id).
- SR4-03: llm_call.workspace_id, so usage is read per workspace.
- SR4-04: author_id / deleted_by_id may go to NULL only from the FK ON DELETE SET NULL action
  (pg_trigger_depth() > 1), never from a direct UPDATE.

Revision ID: 0003_hardening
Revises: 0002_lockdown
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_hardening"
down_revision = "0002_lockdown"
branch_labels = None
depends_on = None

_TABLES = ("note", "comment")

_TRUNCATE_FUNCTION = """
CREATE FUNCTION guard_truncate() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
  IF coalesce(current_setting('dataforce.erasure', true), '') = 'on' THEN
    RETURN NULL;
  END IF;
  RAISE EXCEPTION '% is append-only: TRUNCATE refused', TG_TABLE_NAME;
END
$fn$
"""

# Same function as 0001 except the two NULL rules (marked SR4-04).
_APPEND_ONLY_V2 = """
CREATE OR REPLACE FUNCTION enforce_append_only() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF coalesce(current_setting('dataforce.erasure', true), '') = 'on' THEN
      RETURN OLD;
    END IF;
    RAISE EXCEPTION '% is append-only: DELETE refused (soft delete instead)', TG_TABLE_NAME;
  END IF;

  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
     OR NEW.body IS DISTINCT FROM OLD.body
     OR NEW.corrects_id IS DISTINCT FROM OLD.corrects_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR to_jsonb(NEW) - ARRAY['author_id', 'deleted_at', 'deleted_by_id', 'body', 'corrects_id',
                              'created_at', 'workspace_id', 'id']
        IS DISTINCT FROM
        to_jsonb(OLD) - ARRAY['author_id', 'deleted_at', 'deleted_by_id', 'body', 'corrects_id',
                              'created_at', 'workspace_id', 'id'] THEN
    RAISE EXCEPTION '% is append-only: only a soft delete may change a row', TG_TABLE_NAME;
  END IF;

  -- author_id may only go to NULL, and only from the FK ON DELETE SET NULL action (depth > 1).
  IF NEW.author_id IS DISTINCT FROM OLD.author_id
     AND (NEW.author_id IS NOT NULL OR pg_trigger_depth() <= 1) THEN
    RAISE EXCEPTION '% is append-only: author_id is immutable', TG_TABLE_NAME;
  END IF;

  IF NEW.deleted_at IS DISTINCT FROM OLD.deleted_at
     AND (OLD.deleted_at IS NOT NULL OR NEW.deleted_at IS NULL) THEN
    RAISE EXCEPTION '% is append-only: already deleted', TG_TABLE_NAME;
  END IF;
  -- deleted_by_id is set together with the soft delete; NULL only from the FK action.
  IF NEW.deleted_by_id IS DISTINCT FROM OLD.deleted_by_id THEN
    IF NEW.deleted_by_id IS NULL THEN
      IF pg_trigger_depth() <= 1 THEN
        RAISE EXCEPTION '% is append-only: deleted_by_id is immutable', TG_TABLE_NAME;
      END IF;
    ELSIF NOT (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL) THEN
      RAISE EXCEPTION '% is append-only: deleted_by_id can only be set by the soft delete',
        TG_TABLE_NAME;
    END IF;
  END IF;
  RETURN NEW;
END
$fn$
"""

_APPEND_ONLY_V1 = """
CREATE OR REPLACE FUNCTION enforce_append_only() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF coalesce(current_setting('dataforce.erasure', true), '') = 'on' THEN
      RETURN OLD;
    END IF;
    RAISE EXCEPTION '% is append-only: DELETE refused (soft delete instead)', TG_TABLE_NAME;
  END IF;

  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
     OR NEW.body IS DISTINCT FROM OLD.body
     OR NEW.corrects_id IS DISTINCT FROM OLD.corrects_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR to_jsonb(NEW) - ARRAY['author_id', 'deleted_at', 'deleted_by_id', 'body', 'corrects_id',
                              'created_at', 'workspace_id', 'id']
        IS DISTINCT FROM
        to_jsonb(OLD) - ARRAY['author_id', 'deleted_at', 'deleted_by_id', 'body', 'corrects_id',
                              'created_at', 'workspace_id', 'id'] THEN
    RAISE EXCEPTION '% is append-only: only a soft delete may change a row', TG_TABLE_NAME;
  END IF;

  IF NEW.author_id IS DISTINCT FROM OLD.author_id AND NEW.author_id IS NOT NULL THEN
    RAISE EXCEPTION '% is append-only: author_id is immutable', TG_TABLE_NAME;
  END IF;

  IF NEW.deleted_at IS DISTINCT FROM OLD.deleted_at
     AND (OLD.deleted_at IS NOT NULL OR NEW.deleted_at IS NULL) THEN
    RAISE EXCEPTION '% is append-only: already deleted', TG_TABLE_NAME;
  END IF;
  IF NEW.deleted_by_id IS DISTINCT FROM OLD.deleted_by_id AND NEW.deleted_by_id IS NOT NULL
     AND NOT (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL) THEN
    RAISE EXCEPTION '% is append-only: deleted_by_id can only be set by the soft delete',
      TG_TABLE_NAME;
  END IF;
  RETURN NEW;
END
$fn$
"""


def upgrade() -> None:
    op.execute(_TRUNCATE_FUNCTION)
    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_truncate BEFORE TRUNCATE ON {table} "  # noqa: S608
            "FOR EACH STATEMENT EXECUTE FUNCTION guard_truncate()"
        )
        op.create_index(
            f"uq_{table}_corrects",
            table,
            ["corrects_id"],
            unique=True,
            postgresql_where=sa.text("corrects_id IS NOT NULL"),
        )
    op.execute(_APPEND_ONLY_V2)
    op.add_column(
        "llm_call",
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
        ),
    )
    op.create_index("ix_llm_call_workspace_id", "llm_call", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_call_workspace_id", table_name="llm_call")
    op.drop_column("llm_call", "workspace_id")
    op.execute(_APPEND_ONLY_V1)
    for table in _TABLES:
        op.drop_index(f"uq_{table}_corrects", table_name=table)
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_truncate ON {table}")
    op.execute("DROP FUNCTION IF EXISTS guard_truncate()")
