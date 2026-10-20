"""M6 public demo (docs/M6-ACCOUNTS-ADMIN-CONTRACT.md section E): demo accounts and demo sessions,
and the visitor's own AI key (sealed) on the session.

Both tables already have row-level security (0011_auth); new columns inherit it.

Revision ID: 0015_demo
Revises: 0014_limits_usage
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0015_demo"
down_revision = "0014_limits_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("user_account", "user_session"):
        op.add_column(
            table,
            sa.Column("is_demo", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        )
    op.add_column("user_session", sa.Column("llm_provider", sa.String(length=16), nullable=True))
    op.add_column("user_session", sa.Column("llm_model", sa.String(length=64), nullable=True))
    op.add_column("user_session", sa.Column("llm_key_enc", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_session", "llm_key_enc")
    op.drop_column("user_session", "llm_model")
    op.drop_column("user_session", "llm_provider")
    op.drop_column("user_session", "is_demo")
    op.drop_column("user_account", "is_demo")
