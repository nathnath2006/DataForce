"""M6 accounts (docs/M6-ACCOUNTS-ADMIN-CONTRACT.md): creation codes, join tokens, and the number
of workspaces a person may still create.

Revision ID: 0013_accounts
Revises: 0012_onboarding
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0013_accounts"
down_revision = "0012_onboarding"
branch_labels = None
depends_on = None

TABLES = ("creation_code", "join_token")
_NOW = sa.text("now()")


def upgrade() -> None:
    op.add_column(
        "user_account",
        sa.Column("workspace_credits", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_user_account_credits", "user_account", "workspace_credits >= 0"
    )
    op.create_table(
        "creation_code",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("uses", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "max_uses >= 1 AND max_uses <= 100 AND uses >= 0", name="ck_creation_code_uses"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user_account.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index("ix_creation_code_created_by", "creation_code", ["created_by"])
    op.create_table(
        "join_token",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("uses", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('admin', 'rep')", name="ck_join_token_role"),
        sa.CheckConstraint(
            "max_uses >= 1 AND max_uses <= 50 AND uses >= 0", name="ck_join_token_uses"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user_account.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_join_token_workspace_id", "join_token", ["workspace_id"])
    op.create_index("ix_join_token_created_by", "join_token", ["created_by"])
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")  # noqa: S608


def downgrade() -> None:
    op.drop_table("join_token")
    op.drop_table("creation_code")
    op.drop_constraint("ck_user_account_credits", "user_account", type_="check")
    op.drop_column("user_account", "workspace_credits")
