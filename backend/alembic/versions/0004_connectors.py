"""M1b: TamTam OAuth connection, OAuth flows in flight, enriched contact channels.

Secrets (tokens, client secret, PKCE verifier) and enriched contact values are stored sealed
(Fernet, DATAFORCE_SECRET_KEY): the columns end in `_enc`. The new tables get the same lockdown
as 0002 (RLS on, no policy; the Data API roles have no privileges).

Revision ID: 0004_connectors
Revises: 0003_hardening
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004_connectors"
down_revision = "0003_hardening"
branch_labels = None
depends_on = None

# Tables created here; tests/db/test_migrations.py checks that the TABLES of the lockdown
# migrations together cover every model table.
TABLES = ("connector_credential", "oauth_pending", "contact_channel")


def _id() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def _workspace() -> sa.Column:
    return sa.Column(
        "workspace_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("workspace.id", ondelete="CASCADE"),
        nullable=False,
    )


def _ts(name: str, *, nullable: bool = False, default: bool = True) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.func.now() if default else None,
        nullable=nullable,
    )


def upgrade() -> None:
    op.create_table(
        "connector_credential",
        _id(),
        _workspace(),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("client_secret_enc", sa.Text()),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("access_token_enc", sa.Text(), nullable=False),
        sa.Column("refresh_token_enc", sa.Text()),
        _ts("token_expires_at", nullable=True, default=False),
        sa.Column("scope", sa.Text()),
        sa.Column("tools", postgresql.JSONB()),
        _ts("checked_at", nullable=True, default=False),
        sa.Column("last_error", sa.Text()),
        _ts("connected_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("workspace_id", "provider", name="uq_connector_credential_ws_provider"),
    )
    op.create_table(
        "oauth_pending",
        _id(),
        _workspace(),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("browser_hash", sa.String(64), nullable=False),
        sa.Column("code_verifier_enc", sa.Text(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("client_secret_enc", sa.Text()),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        _ts("created_at"),
        _ts("expires_at", default=False),
    )
    op.create_table(
        "contact_channel",
        _id(),
        _workspace(),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contact.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("value_enc", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("credits_used", sa.Numeric(12, 3), nullable=False),
        sa.Column("raw_tool", sa.String(200)),
        _ts("fetched_at"),
    )
    op.create_index("ix_contact_channel_contact", "contact_channel", ["contact_id"])
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")  # noqa: S608
    # 0002's ALTER DEFAULT PRIVILEGES already keeps anon / authenticated off new tables.


def downgrade() -> None:
    op.drop_index("ix_contact_channel_contact", table_name="contact_channel")
    for table in reversed(TABLES):
        op.drop_table(table)
