"""Mailbox (Gmail, Outlook): connections with sealed tokens and candidate email metadata.

Revision ID: 0010_mailbox
Revises: 0009_m4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_mailbox"
down_revision: str | None = "0009_m4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("mailbox_connection", "mailbox_message")


def upgrade() -> None:
    op.create_table(
        "mailbox_connection",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=True),
        sa.Column("client_secret_enc", sa.Text(), nullable=True),
        sa.Column("account_email_enc", sa.Text(), nullable=True),
        sa.Column("access_token_enc", sa.Text(), nullable=True),
        sa.Column("refresh_token_enc", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("provider IN ('gmail','outlook')", name="ck_mailbox_connection_provider"),
        sa.CheckConstraint(
            "status IN ('configured','connected','needs_reconnect')",
            name="ck_mailbox_connection_status",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "provider", name="uq_mailbox_connection_ws_provider"),
    )
    op.create_table(
        "mailbox_message",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("provider_message_id", sa.String(length=300), nullable=False),
        sa.Column("thread_id", sa.String(length=300), nullable=True),
        sa.Column("from_addr", sa.String(length=320), nullable=False),
        sa.Column("to_addrs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cc_addrs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("snippet", sa.String(length=200), nullable=False),
        sa.Column("suggested_deal_id", sa.UUID(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("linked_activity_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('suggested','linked','ignored')", name="ck_mailbox_message_state"
        ),
        sa.ForeignKeyConstraint(["connection_id"], ["mailbox_connection.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_activity_id"], ["activity.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["suggested_deal_id"], ["deal.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "provider_message_id", name="uq_mailbox_message_ref"),
    )
    op.create_index(
        "ix_mailbox_message_ws_deal",
        "mailbox_message",
        ["workspace_id", "suggested_deal_id"],
        unique=False,
    )
    op.create_index(
        "ix_mailbox_message_activity",
        "mailbox_message",
        ["linked_activity_id"],
        unique=False,
        postgresql_where=sa.text("linked_activity_id IS NOT NULL"),
    )
    op.create_index(
        "ix_mailbox_message_deal",
        "mailbox_message",
        ["suggested_deal_id"],
        unique=False,
        postgresql_where=sa.text("suggested_deal_id IS NOT NULL"),
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")  # noqa: S608


def downgrade() -> None:
    op.drop_table("mailbox_message")
    op.drop_table("mailbox_connection")
