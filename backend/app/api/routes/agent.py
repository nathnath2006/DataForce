"""How to connect an AI assistant (MCP), the tool list and recent calls (M3a)."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentWorkspace, Db
from app.api.schemas_agent import AgentCall, AgentConnect, AgentInfo, AgentTool
from app.db.models import Run
from app.domain.enums import RunKind, RunStatus
from app.mcp_server.config import claude_code_command, claude_desktop_config
from app.mcp_server.registry import load_registry

router = APIRouter(tags=["agent"])


@router.get("/w/{ws}/agent", response_model=AgentInfo)
def agent_info(ws: CurrentWorkspace, db: Db) -> AgentInfo:
    rows = db.scalars(
        select(Run)
        .where(Run.workspace_id == ws.id, Run.kind == RunKind.AGENT_CALL.value)
        .order_by(Run.started_at.desc())
        .limit(20)
    ).all()
    calls = [
        AgentCall(
            at=r.started_at,
            tool=str((r.params or {}).get("tool", "?")),
            ok=r.status == RunStatus.SUCCEEDED.value,
            rows=(r.result or {}).get("rows"),
            duration_ms=r.duration_ms,
        )
        for r in rows
    ]
    return AgentInfo(
        connect=AgentConnect(
            claude_desktop=claude_desktop_config(ws.slug), claude_code=claude_code_command(ws.slug)
        ),
        tools=[
            AgentTool(name=t.name, description=t.description, read_only=True)
            for t in load_registry()
        ],
        recent_calls=calls,
    )
