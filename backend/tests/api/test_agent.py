"""GET /api/w/{ws}/agent."""

from __future__ import annotations

import pytest

from app.domain.enums import RunKind
from app.mcp_server.config import dataforce_bin
from app.services import runs

pytestmark = pytest.mark.integration


def test_agent_info(client, db_session):
    assert client.post("/api/workspaces", json={"slug": "ag1", "name": "A"}).status_code == 201
    other = client.post("/api/workspaces", json={"slug": "ag2", "name": "B"})
    assert other.status_code == 201
    from app.services import workspaces

    w1 = workspaces.get_workspace_by_slug(db_session, "ag1")
    w2 = workspaces.get_workspace_by_slug(db_session, "ag2")
    r = runs.start_run(db_session, RunKind.AGENT_CALL, w1.id, {"tool": "list_flows", "args": {}})
    runs.finish_run(db_session, r, runs.RunStatus.SUCCEEDED, {"ok": True, "rows": 4})
    runs.start_run(db_session, RunKind.AGENT_CALL, w2.id, {"tool": "other_ws"})
    db_session.flush()

    body = client.get("/api/w/ag1/agent").json()
    cfg = body["connect"]["claude_desktop"]["mcpServers"]["dataforce-ag1"]
    assert cfg == {"command": dataforce_bin(), "args": ["mcp", "--workspace", "ag1"]}
    assert body["connect"]["claude_code"].startswith("claude mcp add dataforce-ag1 -- ")
    assert len(body["tools"]) == 14
    assert {"workspace_overview", "run_flow", "search_text"} <= {t["name"] for t in body["tools"]}
    assert all(t["read_only"] and t["description"] for t in body["tools"])
    assert [c["tool"] for c in body["recent_calls"]] == ["list_flows"]
    assert body["recent_calls"][0]["ok"] is True and body["recent_calls"][0]["rows"] == 4
    assert client.get("/api/w/nope/agent").status_code == 404
