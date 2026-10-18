"""Launcher for the e2e test: the real CLI path but with the stub registry."""

from __future__ import annotations

import sys

from app.db import session as db_session
from app.mcp_server.server import build_server
from app.services import workspaces
from tests.mcp.stubs import stub_registry

if __name__ == "__main__":
    with db_session.SessionLocal() as s:
        ws = workspaces.get_workspace_by_slug(s, sys.argv[1])
        assert ws is not None
        ws_id, name = ws.id, ws.name
    build_server(ws_id, name, synthetic=True, registry=stub_registry()).run("stdio")
