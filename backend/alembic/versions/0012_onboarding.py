"""Workspace onboarding: a setup state for workspaces filled in the background, and a fixed
search_path on the two trigger functions (Supabase advisor function_search_path_mutable).

Both function bodies only use built-ins (current_setting, coalesce, to_jsonb, RAISE), which live in
pg_catalog and are always searched, so an empty search_path changes nothing.

Revision ID: 0012_onboarding
Revises: 0011_auth
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0012_onboarding"
down_revision = "0011_auth"
branch_labels = None
depends_on = None

_FUNCTIONS = ("enforce_append_only()", "guard_truncate()")


def upgrade() -> None:
    for fn in _FUNCTIONS:
        op.execute(f"ALTER FUNCTION {fn} SET search_path = ''")
    op.add_column("workspace", sa.Column("setup_state", sa.String(length=16), nullable=True))
    op.create_check_constraint(
        "ck_workspace_setup_state", "workspace", "setup_state IN ('preparing')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_workspace_setup_state", "workspace", type_="check")
    op.drop_column("workspace", "setup_state")
    for fn in _FUNCTIONS:
        op.execute(f"ALTER FUNCTION {fn} RESET search_path")
