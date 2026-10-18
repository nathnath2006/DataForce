"""Connection snippets for AI assistants (CLI `dataforce mcp config` and the API)."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[2]


def dataforce_bin() -> str:
    """Absolute path of this checkout's `dataforce` executable."""
    return str(BACKEND_DIR / ".venv" / "bin" / "dataforce")


def server_name(slug: str) -> str:
    return f"dataforce-{slug}"


def claude_desktop_config(slug: str) -> dict[str, Any]:
    return {
        "mcpServers": {
            server_name(slug): {"command": dataforce_bin(), "args": ["mcp", "--workspace", slug]}
        }
    }


def claude_code_command(slug: str) -> str:
    parts = ["claude", "mcp", "add", server_name(slug), "--", dataforce_bin(), "mcp",
             "--workspace", slug]  # fmt: skip
    return " ".join(shlex.quote(p) for p in parts)


def snippet(slug: str, client: str) -> str:
    if client == "claude-code":
        return claude_code_command(slug)
    return json.dumps(claude_desktop_config(slug), indent=2)
