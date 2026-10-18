"""`dataforce mcp`: serve the read-only agent tools over stdio (stdout is the protocol)."""

from __future__ import annotations

import logging
import sys
from typing import Annotated

import typer
from pydantic import ValidationError

from app.agent import runtime
from app.cli._common import cli_command, fail
from app.config import get_settings
from app.mcp_server.config import snippet
from app.mcp_server.engine import make_factory
from app.mcp_server.server import build_server
from app.services import workspaces

app = typer.Typer(
    help="Let an AI assistant on this computer query one workspace (read-only, stdio).",
    add_completion=False,
    invoke_without_command=True,
)

SETTINGS_ERROR = "the settings are invalid: check backend/.env (run `dataforce config` for details)"

Workspace = Annotated[str, typer.Option("--workspace", "-w", help="Workspace slug to serve.")]


@app.callback()
@cli_command
def serve(ctx: typer.Context, workspace: Workspace = "") -> None:
    """Start the MCP server for a workspace (stdio). Use `mcp config` for the client snippet."""
    if ctx.invoked_subcommand is not None:
        return
    if not workspace:
        raise fail("--workspace SLUG is required")
    try:
        environment = get_settings().environment
    except ValidationError:
        raise fail(SETTINGS_ERROR) from None
    if environment == "demo":
        raise fail("the MCP server is not available with ENVIRONMENT=demo: there is no login")
    factory = make_factory()  # statement timeout on the connection, for flow workers too
    runtime.set_session_factory(factory)
    with factory() as s:
        ws = workspaces.get_workspace_by_slug(s, workspace)
        if ws is None:
            raise fail(f"unknown workspace {workspace!r}")
        ws_id, name, synthetic = ws.id, ws.name, ws.is_demo
    # Logs go to stderr only: stdout carries the protocol.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, force=True)
    build_server(ws_id, name, synthetic=synthetic, factory=factory).run("stdio")


@app.command("config")
def config(
    workspace: Workspace,
    client: Annotated[
        str, typer.Option("--client", help="claude-desktop or claude-code.")
    ] = "claude-desktop",
) -> None:
    """Print the snippet to paste into the assistant's settings."""
    try:
        get_settings()
    except ValidationError:
        raise fail(SETTINGS_ERROR) from None
    if client not in ("claude-desktop", "claude-code"):
        raise fail("--client must be claude-desktop or claude-code")
    typer.echo(snippet(workspace, client))
