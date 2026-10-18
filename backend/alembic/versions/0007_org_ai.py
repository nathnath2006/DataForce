"""Opt-in AI pass over meeting sentences for org statements (docs/ORG-AI-CONTRACT.md): the
workspace switch and the per-transcript cache of verified findings.

Revision ID: 0007_org_ai
Revises: 0006_m2b
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_org_ai"
down_revision = "0006_m2b"
branch_labels = None
depends_on = None

TABLES = ("meeting_org_ai_cache",)

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "llm_credential",
        sa.Column(
            "allow_meeting_org", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.create_table(
        "meeting_org_ai_cache",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "workspace_id", UUID, sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "document_id", UUID, sa.ForeignKey("document.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("findings", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "document_id", "text_sha256", "provider", "model", name="uq_meeting_org_ai_cache"
        ),
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")  # noqa: S608


def downgrade() -> None:
    op.drop_table("meeting_org_ai_cache")
    op.drop_column("llm_credential", "allow_meeting_org")
