"""Lock the schema down for hosted Postgres (SR3-01).

Supabase publishes `public` tables through its Data API to the `anon` / `authenticated` roles.
RLS with no policy denies those roles everything; the app connects as the table owner, which
bypasses RLS. The REVOKE only runs when the roles exist, so local docker is untouched.

Revision ID: 0002_lockdown
Revises: 0001_initial
"""

from __future__ import annotations

from alembic import op

revision = "0002_lockdown"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

# Every table of 0001_initial plus alembic_version. tests/db/test_migrations.py checks this list
# covers every model table.
TABLES = (
    "workspace",
    "app_user",
    "account",
    "contact",
    "deal",
    "note",
    "comment",
    "run",
    "llm_call",
    "alembic_version",
)

_REVOKE = """
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
     AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
    REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
  END IF;
END $$
"""


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")  # noqa: S608
    op.execute(_REVOKE)


def downgrade() -> None:
    # Privileges are not restored: re-granting the Data API roles is never what you want.
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")  # noqa: S608
