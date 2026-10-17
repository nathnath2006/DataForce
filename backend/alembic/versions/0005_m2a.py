"""M2a: companies (accounts grouped under a company), analysis flows with their uploaded files
and external database connections, and the workspace's AI model credential.

Secrets (`*_enc`) are sealed with Fernet (DATAFORCE_SECRET_KEY). The new tables get the same
lockdown as 0002 (RLS on, no policy).

Revision ID: 0005_m2a
Revises: 0004_connectors
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_m2a"
down_revision = "0004_connectors"
branch_labels = None
depends_on = None

# Tables created here (tests/db/test_migrations.py: the lockdown lists cover every model table).
TABLES = ("company", "uploaded_file", "data_connection", "flow", "llm_credential")


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
        "company",
        _id(),
        _workspace(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("siren", sa.String(9)),
        sa.Column("domain", sa.String(253)),
        sa.Column("address_line", sa.Text()),
        sa.Column("postal_code", sa.String(16)),
        sa.Column("city", sa.String(100)),
        sa.Column("country", sa.String(2)),
        sa.Column("naf_code", sa.String(10)),
        sa.Column("legal_category", sa.String(10)),
        sa.Column("size_bracket", sa.String(8)),
        sa.Column("category", sa.String(8)),
        sa.Column("source", sa.String(16), nullable=False),
        _ts("registry_checked_at", nullable=True, default=False),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_company_ws_name", "company", ["workspace_id", "name"])
    op.create_index(
        "uq_company_ws_siren",
        "company",
        ["workspace_id", "siren"],
        unique=True,
        postgresql_where=sa.text("siren IS NOT NULL"),
    )
    op.add_column(
        "account",
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company.id", ondelete="SET NULL"),
        ),
    )
    op.create_index("ix_account_company_id", "account", ["company_id"])

    op.create_table(
        "uploaded_file",
        _id(),
        _workspace(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("sheet", sa.Text()),
        sa.Column("n_rows", sa.Integer()),
        sa.Column("columns", postgresql.JSONB()),
        _ts("created_at"),
    )
    op.create_index("ix_uploaded_file_ws", "uploaded_file", ["workspace_id", "created_at"])

    op.create_table(
        "data_connection",
        _id(),
        _workspace(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("host", sa.String(253), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("database", sa.String(128), nullable=False),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("password_enc", sa.Text()),
        sa.Column("sslmode", sa.String(16), nullable=False),
        _ts("last_test_at", nullable=True, default=False),
        sa.Column("last_test_ok", sa.Boolean()),
        sa.Column("last_error", sa.Text()),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_data_connection_ws_name"),
    )

    op.create_table(
        "flow",
        _id(),
        _workspace(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("graph", postgresql.JSONB(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_flow_ws_name", "flow", ["workspace_id", "name"])

    op.create_table(
        "llm_credential",
        _id(),
        _workspace(),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("api_key_enc", sa.Text(), nullable=False),
        _ts("last_test_at", nullable=True, default=False),
        sa.Column("last_test_ok", sa.Boolean()),
        sa.Column("last_error", sa.Text()),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("workspace_id", name="uq_llm_credential_ws"),
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")  # noqa: S608


def downgrade() -> None:
    for table in ("llm_credential", "flow", "data_connection", "uploaded_file"):
        op.drop_table(table)
    op.drop_index("ix_account_company_id", table_name="account")
    op.drop_column("account", "company_id")
    op.drop_index("uq_company_ws_siren", table_name="company")
    op.drop_index("ix_company_ws_name", table_name="company")
    op.drop_table("company")
