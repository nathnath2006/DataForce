"""M2b: title normalisation (source, flag, AI cache), org-chart proposals with evidence,
imported meeting transcripts (documents + chunks) and themes.

Revision ID: 0006_m2b
Revises: 0005_m2a
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006_m2b"
down_revision = "0005_m2a"
branch_labels = None
depends_on = None

# Tables created here (tests/db/test_migrations.py: the lockdown lists cover every model table).
TABLES = (
    "title_cache",
    "org_proposal",
    "document",
    "document_chunk",
    "theme",
    "theme_assignment",
)

UUID = postgresql.UUID(as_uuid=True)


def _id() -> sa.Column:
    return sa.Column("id", UUID, primary_key=True)


def _workspace() -> sa.Column:
    return sa.Column(
        "workspace_id", UUID, sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )


def _fk(name: str, target: str, ondelete: str, *, nullable: bool = True) -> sa.Column:
    return sa.Column(name, UUID, sa.ForeignKey(target, ondelete=ondelete), nullable=nullable)


def _ts(name: str, *, nullable: bool = False, default: bool = True) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.func.now() if default else None,
        nullable=nullable,
    )


def upgrade() -> None:
    op.add_column("contact", sa.Column("title_source", sa.String(16)))
    op.add_column("contact", sa.Column("title_flag", sa.Text()))

    op.create_table(
        "title_cache",
        _id(),
        _workspace(),
        sa.Column("normalized_title", sa.Text(), nullable=False),
        sa.Column("function", sa.String(16), nullable=False),
        sa.Column("seniority", sa.String(16), nullable=False),
        sa.Column("confidence", sa.String(8), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("workspace_id", "normalized_title", name="uq_title_cache_ws_title"),
    )

    op.create_table(
        "org_proposal",
        _id(),
        _workspace(),
        _fk("account_id", "account.id", "CASCADE", nullable=False),
        _fk("contact_id", "contact.id", "CASCADE", nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        _fk("manager_id", "contact.id", "CASCADE"),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("rule", sa.String(64)),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("candidates", postgresql.JSONB()),
        sa.Column("status", sa.String(16), nullable=False),
        _fk("run_id", "run.id", "SET NULL"),
        _ts("created_at"),
        _ts("decided_at", nullable=True, default=False),
        _fk("decided_by_id", "app_user.id", "SET NULL"),
    )
    op.create_index("ix_org_proposal_account", "org_proposal", ["account_id", "status"])
    op.create_index("ix_org_proposal_contact", "org_proposal", ["contact_id"])
    op.add_column("contact", sa.Column("reports_to_proposal_id", UUID))
    op.create_foreign_key(
        "fk_contact_reports_to_proposal",
        "contact",
        "org_proposal",
        ["reports_to_proposal_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "document",
        _id(),
        _workspace(),
        _fk("account_id", "account.id", "CASCADE", nullable=False),
        _fk("deal_id", "deal.id", "SET NULL"),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("meeting_date", sa.Date()),
        sa.Column("file_name", sa.Text()),
        sa.Column("media_type", sa.String(100)),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("n_chars", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(8)),
        sa.Column("source", sa.String(16), nullable=False),
        _fk("created_by_id", "app_user.id", "SET NULL"),
        _ts("created_at"),
    )
    op.create_index("ix_document_account", "document", ["account_id", "meeting_date"])
    op.create_index("ix_document_deal_id", "document", ["deal_id"])

    op.create_table(
        "document_chunk",
        _id(),
        _workspace(),
        _fk("document_id", "document.id", "CASCADE", nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.Text()),
        _fk("contact_id", "contact.id", "SET NULL"),
        _fk("user_id", "app_user.id", "SET NULL"),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index("ix_document_chunk_document", "document_chunk", ["document_id", "seq"])

    op.create_table(
        "theme",
        _id(),
        _workspace(),
        _fk("run_id", "run.id", "CASCADE", nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("named_by", sa.String(16), nullable=False),
        sa.Column("top_terms", postgresql.JSONB(), nullable=False),
        sa.Column("n_chunks", sa.Integer(), nullable=False),
        sa.Column("n_documents", sa.Integer(), nullable=False),
        sa.Column("n_accounts", sa.Integer(), nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_theme_run", "theme", ["run_id"])

    op.create_table(
        "theme_assignment",
        sa.Column(
            "theme_id",
            UUID,
            sa.ForeignKey("theme.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "chunk_id",
            UUID,
            sa.ForeignKey("document_chunk.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        _workspace(),
        sa.Column("weight", sa.Float(), nullable=False),
    )
    op.create_index("ix_theme_assignment_chunk", "theme_assignment", ["chunk_id"])

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")  # noqa: S608


def downgrade() -> None:
    op.drop_constraint("fk_contact_reports_to_proposal", "contact", type_="foreignkey")
    op.drop_column("contact", "reports_to_proposal_id")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.drop_column("contact", "title_flag")
    op.drop_column("contact", "title_source")
