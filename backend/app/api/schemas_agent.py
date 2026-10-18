"""Schemas for the agent / MCP connection endpoint (docs/M3A-CONTRACT.md section 4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AgentConnect(BaseModel):
    claude_desktop: dict[str, Any]
    claude_code: str


class AgentTool(BaseModel):
    name: str
    description: str
    read_only: bool


class AgentCall(BaseModel):
    at: datetime
    tool: str
    ok: bool
    rows: int | None
    duration_ms: int | None


class AgentInfo(BaseModel):
    connect: AgentConnect
    tools: list[AgentTool]
    recent_calls: list[AgentCall]
