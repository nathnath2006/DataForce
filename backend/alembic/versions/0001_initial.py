"""Initial schema: minimal CRM + runs + LLM usage, with append-only notes and comments.

Mirrors app/db/models.py exactly (tests/db/test_migrations.py compares them).

Append-only (ARCHITECTURE 3.1): a plpgsql trigger on `note` and `comment` makes a row immutable
except for the one-time soft delete and the FK SET NULL when a user is deleted. DELETE is refused
unless the transaction set `dataforce.erasure = 'on'`, which only the erasure services do (GDPR
erasure of a contact / account, and workspace deletion).

Revision ID: 0001_initial
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_NOW = sa.text("now()")

# One function for both tables: the column sets are identical. IS DISTINCT FROM handles NULLs.
_FUNCTION = """
CREATE FUNCTION enforce_append_only() RETURNS trigger LANGUAGE plpgsql AS $fn$
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

  -- author_id may only go to NULL (user deleted).
  IF NEW.author_id IS DISTINCT FROM OLD.author_id AND NEW.author_id IS NOT NULL THEN
    RAISE EXCEPTION '% is append-only: author_id is immutable', TG_TABLE_NAME;
  END IF;

  -- Soft delete: deleted_at goes from NULL to a value, once.
  IF NEW.deleted_at IS DISTINCT FROM OLD.deleted_at
     AND (OLD.deleted_at IS NOT NULL OR NEW.deleted_at IS NULL) THEN
    RAISE EXCEPTION '% is append-only: already deleted', TG_TABLE_NAME;
  END IF;
  -- deleted_by_id is set together with that soft delete, or goes to NULL (user deleted).
  IF NEW.deleted_by_id IS DISTINCT FROM OLD.deleted_by_id AND NEW.deleted_by_id IS NOT NULL
     AND NOT (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL) THEN
    RAISE EXCEPTION '% is append-only: deleted_by_id can only be set by the soft delete',
      TG_TABLE_NAME;
  END IF;
  RETURN NEW;
END
$fn$
"""


def _pk() -> sa.Column:
    return sa.Column("id", _UUID, primary_key=True)


def _ws() -> sa.Column:
    return sa.Column(
        "workspace_id", _UUID, sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )


def _created(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=_NOW, nullable=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "workspace",
        _pk(),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("is_demo", sa.Boolean, nullable=False),
        _created(),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "app_user",
        _pk(),
        _ws(),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("email", sa.String(320)),
        sa.Column("role", sa.String(16), nullable=False),
        _created(),
        sa.UniqueConstraint("workspace_id", "email", name="uq_app_user_ws_email"),
    )
    op.create_table(
        "account",
        _pk(),
        _ws(),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("domain", sa.String(253)),
        sa.Column("industry", sa.String(100)),
        sa.Column("segment", sa.String(16)),
        sa.Column("employee_count", sa.Integer),
        sa.Column("region", sa.String(100)),
        sa.Column("country", sa.String(2)),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("external_ref", sa.String(200)),
        _created(),
        _created("updated_at"),
    )
    op.create_index("ix_account_ws_name", "account", ["workspace_id", "name"])
    op.create_table(
        "contact",
        _pk(),
        _ws(),
        sa.Column(
            "account_id", _UUID, sa.ForeignKey("account.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("full_name", sa.Text, nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("title_function", sa.String(16)),
        sa.Column("title_seniority", sa.String(16)),
        sa.Column("reports_to_id", _UUID, sa.ForeignKey("contact.id", ondelete="SET NULL")),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_ref", sa.Text),
        _created(),
        _created("updated_at"),
        sa.CheckConstraint(
            "reports_to_id IS NULL OR reports_to_id <> id", name="ck_contact_not_self"
        ),
    )
    op.create_index("ix_contact_account", "contact", ["account_id"])
    op.create_table(
        "deal",
        _pk(),
        _ws(),
        sa.Column(
            "account_id", _UUID, sa.ForeignKey("account.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("owner_id", _UUID, sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("amount_eur", sa.Numeric(14, 2)),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("lead_source", sa.String(16)),
        sa.Column("created_on", sa.Date, nullable=False),
        sa.Column("closed_on", sa.Date),
        sa.Column("lost_reason", sa.Text),
        sa.Column("source", sa.String(16), nullable=False),
        _created(),
        _created("updated_at"),
        sa.CheckConstraint(
            "closed_on IS NULL OR closed_on >= created_on", name="ck_deal_closed_after_created"
        ),
        sa.CheckConstraint("amount_eur IS NULL OR amount_eur >= 0", name="ck_deal_amount_positive"),
    )
    op.create_index("ix_deal_ws_stage", "deal", ["workspace_id", "stage"])
    op.create_index("ix_deal_account", "deal", ["account_id"])

    for table, parent, index in (
        ("note", "contact", "ix_note_contact"),
        ("comment", "account", "ix_comment_account"),
    ):
        op.create_table(
            table,
            _pk(),
            _ws(),
            sa.Column(
                f"{parent}_id",
                _UUID,
                sa.ForeignKey(f"{parent}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("author_id", _UUID, sa.ForeignKey("app_user.id", ondelete="SET NULL")),
            sa.Column("body", sa.Text, nullable=False),
            sa.Column("corrects_id", _UUID, sa.ForeignKey(f"{table}.id", ondelete="CASCADE")),
            _created(),
            sa.Column("deleted_at", sa.DateTime(timezone=True)),
            sa.Column("deleted_by_id", _UUID, sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        )
        op.create_index(index, table, [f"{parent}_id", "created_at"])

    op.create_table(
        "run",
        _pk(),
        sa.Column("workspace_id", _UUID, sa.ForeignKey("workspace.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("params", postgresql.JSONB, nullable=False),
        sa.Column("result", postgresql.JSONB),
        _created("started_at"),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("error", sa.Text),
    )
    op.create_table(
        "llm_call",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_id", _UUID, sa.ForeignKey("run.id", ondelete="SET NULL")),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("error", sa.Text),
        _created(),
    )

    op.execute(_FUNCTION)
    for table in ("note", "comment"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "  # noqa: S608
            "FOR EACH ROW EXECUTE FUNCTION enforce_append_only()"
        )


def downgrade() -> None:
    for table in ("comment", "note"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS enforce_append_only()")
    for table in (
        "llm_call",
        "run",
        "comment",
        "note",
        "deal",
        "contact",
        "account",
        "app_user",
        "workspace",
    ):
        op.drop_table(table)
