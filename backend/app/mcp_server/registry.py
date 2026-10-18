"""Adapter over agent A's `TOOLS` registry (`app/agent/tools.py`)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class ToolSpec:
    name: str
    fn: Callable[..., Any]
    args_model: type[BaseModel]
    result_model: Any
    description: str
    read_only_tx: bool  # open the transaction READ ONLY (False for tools that insert a run row)
    idempotent: bool


def normalize(tools: Mapping[str, Any] | Iterable[Any]) -> list[ToolSpec]:
    """Accepts `TOOLS` (dict of agent ToolSpec) or an iterable of them."""
    items = tools.values() if isinstance(tools, Mapping) else tools
    return [
        ToolSpec(
            name=t.name,
            fn=t.fn,
            args_model=t.args_model,
            result_model=getattr(t, "result_model", None),
            description=t.description,
            read_only_tx=not t.writes_run,
            idempotent=t.idempotent,
        )
        for t in items
    ]


def load_registry() -> list[ToolSpec]:
    from app.agent.tools import TOOLS

    return normalize(TOOLS)
