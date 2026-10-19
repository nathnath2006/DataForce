"""M5 login (docs/M5-LOGIN-AND-UI-CONTRACT.md): user accounts, workspace memberships, sessions,
and the account owner (backfilled from the owner of the account's most recent deal).

Revision ID: 0011_auth
Revises: 0010_mailbox
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011_auth"
down_revision = "0010_mailbox"
branch_labels = None
depends_on = None

TABLES = ("user_account", "membership", "user_session")
_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "user_account",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=300), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "membership",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("user_account_id", sa.UUID(), nullable=False),
        sa.Column("app_user_id", sa.UUID(), nullable=True),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column("see_all", sa.Boolean(), nullable=False),
        sa.Column("delete_own", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.CheckConstraint("role IN ('admin', 'rep')", name="ck_membership_role"),
        sa.ForeignKeyConstraint(["app_user_id"], ["app_user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_account_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_account_id", "workspace_id", name="uq_membership_user_ws"),
        sa.UniqueConstraint("workspace_id", "app_user_id", name="uq_membership_ws_app_user"),
    )
    op.create_table(
        "user_session",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_account_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=_NOW,
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_agent", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["user_account_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_user_session_user_account_id"), "user_session", ["user_account_id"], unique=False
    )
    op.add_column("account", sa.Column("owner_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "account_owner_id_fkey", "account", "app_user", ["owner_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index(
        "ix_account_owner",
        "account",
        ["owner_id"],
        unique=False,
        postgresql_where=sa.text("owner_id IS NOT NULL"),
    )
    op.create_index(
        "ix_membership_app_user",
        "membership",
        ["app_user_id"],
        unique=False,
        postgresql_where=sa.text("app_user_id IS NOT NULL"),
    )
    # the owner of the account's most recent deal (ties: the latest created)
    op.execute(
        """
        UPDATE account a SET owner_id = d.owner_id
        FROM (
            SELECT DISTINCT ON (account_id) account_id, owner_id
            FROM deal WHERE owner_id IS NOT NULL
            ORDER BY account_id, created_on DESC, created_at DESC
        ) d
        WHERE d.account_id = a.id AND a.owner_id IS NULL
        """
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")  # noqa: S608


def downgrade() -> None:
    op.drop_index("ix_membership_app_user", table_name="membership")
    op.drop_index("ix_account_owner", table_name="account")
    op.drop_constraint("account_owner_id_fkey", "account", type_="foreignkey")
    op.drop_column("account", "owner_id")
    op.drop_index(op.f("ix_user_session_user_account_id"), table_name="user_session")
    op.drop_table("user_session")
    op.drop_table("membership")
    op.drop_table("user_account")
