"""Doubles for the MCP session (duck-typed like mcp.ClientSession) and settings."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

from app.config import Settings


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def tool(name: str, description: str = "", schema: dict | None = None, camel: bool = False):
    key = "inputSchema" if camel else "input_schema"
    return SimpleNamespace(name=name, description=description, **{key: schema})


def text_result(payload: Any, *, error: bool = False, camel: bool = False):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    key = "isError" if camel else "is_error"
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        **{key: error},
        structured_content=None,
    )


class FakeSession:
    def __init__(self, tools: list, results: dict[str, Any] | None = None):
        self.tools = tools
        self.results = results or {}
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self):
        return SimpleNamespace(tools=self.tools, next_cursor=None)

    async def call_tool(self, name: str, arguments: dict | None = None):
        self.calls.append((name, arguments or {}))
        result = self.results[name]
        return result(arguments) if callable(result) else result


def factory_for(session):
    """(session_factory, opened) where `opened` counts connections."""
    opened: list[int] = []

    @asynccontextmanager
    async def factory():
        opened.append(1)
        yield session

    return factory, opened
