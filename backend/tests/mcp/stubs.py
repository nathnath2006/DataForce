"""A small stub registry (same shape as app/agent/tools.py) for tests."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.tools import ToolSpec
from app.db.models import Workspace
from app.mcp_server.registry import normalize
from app.services.errors import NotFoundError


class NoArgs(BaseModel):
    pass


class ListArgs(BaseModel):
    query: str = Field(default="", max_length=100)
    limit: int = Field(default=50, ge=1, le=500)


class GetArgs(BaseModel):
    item_id: uuid.UUID


def workspace_overview(session: Session, ws_id: uuid.UUID, args: NoArgs) -> dict[str, Any]:
    """Counts for the workspace."""
    ws = session.scalar(select(Workspace).where(Workspace.id == ws_id))
    return {"data": {"name": ws.name, "kind": "exact_count"}, "computed_by": "code",
            "notes": [], "untrusted_fields": []}  # fmt: skip


def search_companies(session: Session, ws_id: uuid.UUID, args: ListArgs) -> dict[str, Any]:
    """Search companies by name."""
    rows = [{"name": f"Acme {i}"} for i in range(min(args.limit, 3))]
    return {"data": rows, "computed_by": "code", "notes": [], "untrusted_fields": []}


def get_company(session: Session, ws_id: uuid.UUID, args: GetArgs) -> dict[str, Any]:
    """One company."""
    raise NotFoundError("company not found")


def try_write(session: Session, ws_id: uuid.UUID, args: NoArgs) -> dict[str, Any]:
    """Tries a write: must fail in a read-only transaction."""
    session.execute(Workspace.__table__.update().values(name="hacked"))
    return {"data": None}


def boom(session: Session, ws_id: uuid.UUID, args: NoArgs) -> dict[str, Any]:
    """Crashes."""
    raise RuntimeError("secret internals SELECT * FROM x")


STUB_TOOLS = {
    f.__name__: ToolSpec(f.__name__, f.__doc__ or "", a, None, f, writes_run=False)
    for f, a in (
        (workspace_overview, NoArgs),
        (search_companies, ListArgs),
        (get_company, GetArgs),
        (try_write, NoArgs),
        (boom, NoArgs),
    )
}


def stub_registry():
    return normalize(STUB_TOOLS)
