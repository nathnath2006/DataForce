"""M6 limits and usage (docs/M6-ACCOUNTS-ADMIN-CONTRACT.md section B): admin-editable limits with
an audit trail, the person behind each AI call, model prices, and the `in_progress` task status.

Revision ID: 0014_limits_usage
Revises: 0013_accounts
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0014_limits_usage"
down_revision = "0013_accounts"
branch_labels = None
depends_on = None

TABLES = ("setting_override", "setting_override_audit", "model_price")
_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "setting_override",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["user_account.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_setting_override_ws",
        "setting_override",
        ["key", "workspace_id"],
        unique=True,
        postgresql_where=sa.text("workspace_id IS NOT NULL"),
    )
    op.create_index(
        "uq_setting_override_global",
        "setting_override",
        ["key"],
        unique=True,
        postgresql_where=sa.text("workspace_id IS NULL"),
    )
    op.create_table(
        "setting_override_audit",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("changed_by", sa.UUID(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by"], ["user_account.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "model_price",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("input_per_mtok_eur", sa.Numeric(12, 4), nullable=False),
        sa.Column("output_per_mtok_eur", sa.Numeric(12, 4), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["user_account.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "model", name="uq_model_price"),
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")  # noqa: S608

    op.add_column("llm_call", sa.Column("user_account_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "llm_call_user_account_id_fkey",
        "llm_call",
        "user_account",
        ["user_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_llm_call_user_account_id", "llm_call", ["user_account_id"])

    op.drop_constraint("ck_task_status", "task", type_="check")
    op.create_check_constraint(
        "ck_task_status",
        "task",
        "status IN ('suggested','open','in_progress','done','dismissed')",
    )


def downgrade() -> None:
    op.execute("UPDATE task SET status = 'open' WHERE status = 'in_progress'")
    op.drop_constraint("ck_task_status", "task", type_="check")
    op.create_check_constraint(
        "ck_task_status", "task", "status IN ('suggested','open','done','dismissed')"
    )
    op.drop_index("ix_llm_call_user_account_id", table_name="llm_call")
    op.drop_constraint("llm_call_user_account_id_fkey", "llm_call", type_="foreignkey")
    op.drop_column("llm_call", "user_account_id")
    op.drop_table("model_price")
    op.drop_table("setting_override_audit")
    op.drop_table("setting_override")
