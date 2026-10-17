"""Admin: database size against the hosting quota."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# Fixed statement, no interpolation. Only tables of the public schema.
_TABLES_SQL = text(
    "SELECT c.relname AS name, pg_total_relation_size(c.oid) AS bytes, "
    "c.reltuples::bigint AS rows_estimate "
    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relkind = 'r' "
    "ORDER BY bytes DESC, name"
)


def db_size(session: Session, quota_mb: int) -> dict[str, Any]:
    """Total database size, share of `quota_mb` used, and the size of each table."""
    total = int(session.execute(text("SELECT pg_database_size(current_database())")).scalar_one())
    tables = [
        {"name": r.name, "bytes": int(r.bytes), "rows_estimate": max(0, int(r.rows_estimate))}
        for r in session.execute(_TABLES_SQL)
    ]
    quota_bytes = quota_mb * 1024 * 1024
    return {
        "size_bytes": total,
        "size_mb": round(total / 1024 / 1024, 2),
        "quota_mb": quota_mb,
        "used_pct": round(100 * total / quota_bytes, 2) if quota_bytes else None,
        "tables": tables,
    }
