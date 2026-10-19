"""Indexes: `workspace_id` on the big tables and every ON DELETE CASCADE / SET NULL foreign key
that had none (a parent delete scanned the child table: workspace delete took over 60 s at 10x).
Audit PERF-B-02 and PERF-B-04. The nullable foreign keys get partial indexes.

Revision ID: 0008_indexes
Revises: 0007_org_ai
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_indexes"
down_revision = "0007_org_ai"
branch_labels = None
depends_on = None

# (index name, table, columns)
PLAIN = (
    ("ix_contact_ws_name", "contact", ("workspace_id", "full_name", "id")),
    ("ix_document_ws_date", "document", ("workspace_id", "meeting_date")),
    ("ix_document_chunk_ws", "document_chunk", ("workspace_id",)),
    ("ix_comment_ws", "comment", ("workspace_id",)),
    ("ix_contact_channel_ws", "contact_channel", ("workspace_id",)),
    ("ix_note_ws", "note", ("workspace_id",)),
    ("ix_meeting_org_ai_cache_ws", "meeting_org_ai_cache", ("workspace_id",)),
    ("ix_oauth_pending_ws", "oauth_pending", ("workspace_id",)),
    ("ix_org_proposal_ws", "org_proposal", ("workspace_id",)),
    ("ix_theme_ws", "theme", ("workspace_id",)),
    ("ix_theme_assignment_ws", "theme_assignment", ("workspace_id",)),
)
# (index name, table, nullable column): partial, `WHERE column IS NOT NULL`
PARTIAL = (
    ("ix_comment_author", "comment", "author_id"),
    ("ix_comment_deleted_by", "comment", "deleted_by_id"),
    ("ix_contact_reports_to", "contact", "reports_to_id"),
    ("ix_contact_reports_to_proposal", "contact", "reports_to_proposal_id"),
    ("ix_deal_owner", "deal", "owner_id"),
    ("ix_document_created_by", "document", "created_by_id"),
    ("ix_document_chunk_contact", "document_chunk", "contact_id"),
    ("ix_document_chunk_user", "document_chunk", "user_id"),
    ("ix_llm_call_run", "llm_call", "run_id"),
    ("ix_note_author", "note", "author_id"),
    ("ix_note_deleted_by", "note", "deleted_by_id"),
    ("ix_org_proposal_decided_by", "org_proposal", "decided_by_id"),
    ("ix_org_proposal_manager", "org_proposal", "manager_id"),
    ("ix_org_proposal_run", "org_proposal", "run_id"),
)


def upgrade() -> None:
    for name, table, columns in PLAIN:
        op.create_index(name, table, list(columns))
    op.create_index(
        "ix_run_ws_kind_started",
        "run",
        ["workspace_id", "kind", sa.text("started_at DESC")],
    )
    for name, table, column in PARTIAL:
        op.create_index(name, table, [column], postgresql_where=sa.text(f"{column} IS NOT NULL"))


def downgrade() -> None:
    for name, table, _column in reversed(PARTIAL):
        op.drop_index(name, table_name=table)
    op.drop_index("ix_run_ws_kind_started", table_name="run")
    for name, table, _columns in reversed(PLAIN):
        op.drop_index(name, table_name=table)
