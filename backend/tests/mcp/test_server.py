"""MCP server: in-process (stub registry) and real stdio subprocess tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from app.cli import app as cli_app
from app.db.models import Run, Workspace
from app.db.session import get_engine
from app.domain.enums import RunKind
from app.mcp_server.config import claude_code_command, claude_desktop_config, dataforce_bin
from app.mcp_server.server import build_server
from app.services import workspaces
from tests.mcp.stubs import stub_registry

pytestmark = pytest.mark.integration
BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def committed_ws(test_database_url, engine):
    """A workspace committed to the test DB (a subprocess cannot see rolled-back data)."""
    factory = sessionmaker(bind=get_engine(test_database_url), expire_on_commit=False)
    slug = "mcp-e2e"
    with factory() as s:
        workspaces.create_workspace(s, slug, "MCP E2E")
        s.commit()
    yield slug, factory
    with factory() as s:
        workspaces.delete_workspace(s, slug)
        s.commit()


def _params(test_database_url, *args, env=None):
    return StdioServerParameters(
        command=sys.executable,
        args=list(args),
        cwd=str(BACKEND),
        env={"DATABASE_URL": test_database_url, "PYTHONPATH": str(BACKEND), **(env or {})},
    )


def _run(coro_fn):
    return anyio.run(coro_fn)


def test_e2e_stub_registry_over_stdio(committed_ws, test_database_url):
    slug, factory = committed_ws

    async def go():
        params = _params(test_database_url, "-m", "tests.mcp.stub_server", slug)
        async with stdio_client(params) as (r, w), ClientSession(r, w) as client:
            init = await client.initialize()
            assert "_untrusted" in init.instructions and "SYNTHETIC" in init.instructions
            tools = (await client.list_tools()).tools
            names = {t.name for t in tools}
            assert {"workspace_overview", "search_companies", "get_company"} <= names
            for t in tools:
                a = t.annotations
                assert a.read_only_hint is True and a.destructive_hint is False
                assert a.open_world_hint is False and t.description
            ov = await client.call_tool("workspace_overview", {})
            assert not ov.is_error
            assert ov.structured_content["data"]["name"] == "MCP E2E"
            sc = await client.call_tool("search_companies", {"limit": 2})
            assert len(sc.structured_content["data"]) == 2
            bad = await client.call_tool("search_companies", {"limit": 9999})
            assert bad.is_error
            nf = await client.call_tool(
                "get_company", {"item_id": "00000000-0000-0000-0000-000000000000"}
            )
            assert nf.is_error and "company not found" in nf.content[0].text
            w = await client.call_tool("try_write", {})
            assert w.is_error
            b = await client.call_tool("boom", {})
            assert b.is_error and "SELECT" not in b.content[0].text

    _run(go)
    with factory() as s:
        rows = s.scalars(select(Run).where(Run.kind == RunKind.AGENT_CALL.value)).all()
        mine = [r for r in rows if r.workspace_id == workspaces.get_workspace_by_slug(s, slug).id]
        by_tool = {r.params["tool"]: r for r in mine}
        assert by_tool["workspace_overview"].status == "succeeded"
        assert by_tool["search_companies"].result["rows"] in (2, 3)
        assert by_tool["get_company"].status == "failed"
        assert by_tool["boom"].status == "failed"
        assert by_tool["try_write"].status == "failed"
        assert by_tool["workspace_overview"].duration_ms is not None
        assert "Acme" not in str(by_tool["search_companies"].result)  # no row data
        # the write attempt did not change anything
        assert s.scalar(select(Workspace.name).where(Workspace.slug == slug)) == "MCP E2E"


def test_stdout_is_only_protocol(committed_ws, test_database_url):
    slug, _ = committed_ws
    import json
    import subprocess

    req = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]  # fmt: skip
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.mcp.stub_server", slug],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": test_database_url, "PYTHONPATH": str(BACKEND)},
    )  # fmt: skip
    try:
        proc.stdin.write("\n".join(json.dumps(m) for m in req) + "\n")
        proc.stdin.flush()
        lines = [proc.stdout.readline(), proc.stdout.readline()]
        for ln in lines:
            assert json.loads(ln)["jsonrpc"] == "2.0"
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
        assert proc.stdout.read().strip() == ""
        proc.stderr.close()
        proc.stdout.close()


REAL_TOOLS = {
    "workspace_overview", "search_companies", "get_company", "get_account", "list_deals",
    "pipeline_summary", "compare_groups", "run_scan", "list_flows", "run_flow",
    "list_meetings", "get_meeting", "get_themes", "search_text",
}  # fmt: skip


@pytest.fixture
def demo_ws(test_database_url, engine):
    from app.demo.generator import generate
    from app.demo.loader import load_dataset

    factory = sessionmaker(bind=get_engine(test_database_url), expire_on_commit=False)
    slug = "mcp-real"
    with factory() as s:
        load_dataset(s, generate("planted", 5, 60), workspace_slug=slug)
        s.commit()
    yield slug, factory
    with factory() as s:
        workspaces.delete_workspace(s, slug)
        s.commit()


def test_cli_real_tools_over_stdio(demo_ws, test_database_url):
    slug, factory = demo_ws
    outputs: list[str] = []

    async def go():
        params = StdioServerParameters(
            command=str(Path(sys.executable).parent / "dataforce"),
            args=["mcp", "--workspace", slug],
            cwd=str(BACKEND),
            env={"DATABASE_URL": test_database_url},
        )
        async with stdio_client(params) as (r, w), ClientSession(r, w) as client:
            await client.initialize()
            tools = (await client.list_tools()).tools
            assert {t.name for t in tools} == REAL_TOOLS
            for t in tools:
                a = t.annotations
                assert a.read_only_hint is True and a.destructive_hint is False
                assert a.open_world_hint is False and t.description
            by = {t.name: t for t in tools}
            assert by["workspace_overview"].annotations.idempotent_hint is True
            assert by["run_scan"].annotations.idempotent_hint is False

            async def call(name, args):
                res = await client.call_tool(name, args)
                assert not res.is_error, res.content
                sc = res.structured_content
                assert sc["computed_by"] == "code"
                outputs.append(str(res.content) + str(sc))
                return sc

            await call("workspace_overview", {})
            deals = await call("list_deals", {"limit": 3})
            rows = deals["data"]["deals"] if "deals" in deals["data"] else deals["data"]["rows"]
            assert len(rows) == 3
            acc_id = rows[0]["account_id"]
            acc = await call("get_account", {"account_id": acc_id})
            assert acc["data"]
            await call("search_text", {"query": "ab", "limit": 5})

    anyio.run(go)
    from app.db.models import Run

    with factory() as s:
        ws = workspaces.get_workspace_by_slug(s, slug)
        tools_called = [
            r.params["tool"]
            for r in s.scalars(
                select(Run)
                .where(Run.workspace_id == ws.id, Run.kind == RunKind.AGENT_CALL.value)
                .order_by(Run.started_at)
            )
        ]
        assert tools_called == ["workspace_overview", "list_deals", "get_account", "search_text"]
        from app.db.models import ContactChannel

        values = [c.value for c in s.scalars(select(ContactChannel)) if getattr(c, "value", None)]
    blob = "\n".join(outputs)
    assert "@" not in blob or all(v not in blob for v in values)
    assert "contact_channel" not in blob


def test_unknown_workspace_refuses(test_database_url, engine):
    r = CliRunner().invoke(cli_app, ["mcp", "--workspace", "nope-nope"])
    assert r.exit_code == 1
    assert "unknown workspace" in r.output


def test_demo_environment_refuses(monkeypatch, engine):
    from types import SimpleNamespace

    monkeypatch.setattr("app.cli.mcp.get_settings", lambda: SimpleNamespace(environment="demo"))
    r = CliRunner().invoke(cli_app, ["mcp", "--workspace", "x"])
    assert r.exit_code == 1 and "ENVIRONMENT=demo" in r.output


def test_missing_workspace_option_refuses():
    r = CliRunner().invoke(cli_app, ["mcp"])
    assert r.exit_code == 1


def test_config_snippets():
    out = CliRunner().invoke(cli_app, ["mcp", "config", "--workspace", "acme"])
    assert out.exit_code == 0
    import json

    cfg = json.loads(out.stdout)
    entry = cfg["mcpServers"]["dataforce-acme"]
    assert entry == {"command": dataforce_bin(), "args": ["mcp", "--workspace", "acme"]}
    assert os.path.isabs(entry["command"])
    code = CliRunner().invoke(cli_app, ["mcp", "config", "-w", "acme", "--client", "claude-code"])
    assert code.stdout.strip() == claude_code_command("acme")
    assert code.stdout.startswith("claude mcp add dataforce-acme -- ")
    assert claude_desktop_config("acme") == cfg
    assert CliRunner().invoke(cli_app, ["mcp", "config", "-w", "a", "--client", "x"]).exit_code == 1


def test_in_process_read_only_and_audit(db_session: Session, session_factory, ws_id):
    import asyncio

    server = build_server(ws_id, "T", registry=stub_registry(), factory=session_factory)

    async def go():
        res = await server.call_tool("search_companies", {"limit": 1})
        return res

    asyncio.run(go())
    runs = db_session.scalars(select(Run).where(Run.workspace_id == ws_id)).all()
    assert [r.params["tool"] for r in runs] == ["search_companies"]
    assert runs[0].params["args"]["limit"] == 1
