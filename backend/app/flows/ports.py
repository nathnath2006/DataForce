"""Seams between the pure flow engine (agent E) and the database-backed sources (agent F).

Contract (owned by the tech lead). The engine never imports SQLAlchemy or the API: it receives a
`SourceLoader` and returns `NodeResult`s.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from app.domain.schemas import GateConfig
from app.flows.schemas import CrmSource, FileSource, PostgresSource

if TYPE_CHECKING:
    import pandas as pd


class SourceError(Exception):
    """A dataset could not be read. The message is shown to the user: it must never contain a
    password, a connection string or a stack trace."""


class SourceLoader(Protocol):
    def load(self, source: CrmSource | FileSource | PostgresSource, max_rows: int) -> pd.DataFrame:
        """Return at most `max_rows` rows (set `df.attrs["capped"] = True` when rows were cut).
        Raise SourceError on any failure."""
        ...


@dataclass(frozen=True)
class FlowLimits:
    max_rows: int = 200_000
    timeout_s: float = 60.0
    preview_rows: int = 100


# Signature implemented by app/flows/engine.py (agent E):
#
#   def run_graph(
#       graph: FlowGraph,
#       loader: SourceLoader,
#       gates: GateConfig,
#       limits: FlowLimits,
#       target: str | None = None,
#   ) -> dict[str, NodeResult]
#
# Runs the nodes needed for `target` (or every node when None) in topological order. A failing
# node gets status "error" and its descendants "skipped"; the run itself never raises for a
# user mistake. The deadline (limits.timeout_s) is checked between nodes.
__all__ = ["FlowLimits", "GateConfig", "SourceError", "SourceLoader"]
