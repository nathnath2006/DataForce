"""Load the rows a visualization reads: a CRM table through the flow loaders (same caps), or the
output of one node of a saved flow, run with the flow engine and its limits. Workspace-scoped."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy.orm import Session

from app.api.schemas_viz import CrmRef, FlowRef
from app.auth.viewer import Viewer
from app.config import Settings
from app.flows.ports import FlowLimits, SourceError
from app.flows.schemas import CrmSource, FileSource, PostgresSource
from app.flows.sources.loader import DbSourceLoader
from app.services import flows
from app.services import limits as limits_service
from app.services.errors import InvalidInputError
from app.stats.engine import gate_config_from_settings

TIME_BUDGET_S = 20.0  # a visualization must answer quickly; flows have their own, longer limit
SLOT_WAIT_S = 15.0  # how long a tile waits for a free analysis slot before giving up


@dataclass
class Loaded:
    df: pd.DataFrame
    truncated: bool
    notes: list[str] = field(default_factory=list)


class _Tracking:
    """Wraps the loader to learn whether any dataset hit the row cap."""

    def __init__(self, inner: DbSourceLoader) -> None:
        self._inner = inner
        self.capped = False

    def load(self, source: CrmSource | FileSource | PostgresSource, max_rows: int) -> pd.DataFrame:
        df = self._inner.load(source, max_rows)
        if df.attrs.get("capped"):
            self.capped = True
        return df


def _call_with_budget(
    fn: Callable[[], object], budget: float, slot: threading.BoundedSemaphore | None = None
) -> object:
    """The slot (already taken) is released when the thread ends, not when the wait does."""
    box: dict[str, object] = {}

    def work() -> None:
        try:
            box["v"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
            box["e"] = exc
        finally:
            if slot is not None:
                slot.release()

    t = threading.Thread(target=work, name="viz-query", daemon=True)
    t.start()
    t.join(budget)
    if t.is_alive():
        raise InvalidInputError(f"the query did not finish within {budget:g} s; add a filter")
    if "e" in box:
        raise box["e"]  # type: ignore[misc]
    return box["v"]


def _take(slot: threading.BoundedSemaphore) -> None:
    """A canvas sends one query per tile at once: wait briefly for a slot instead of failing."""
    if not slot.acquire(timeout=SLOT_WAIT_S):
        raise InvalidInputError("another analysis is still running, try again in a moment")


def load(
    db: Session,
    ws_id: uuid.UUID,
    source: CrmRef | FlowRef,
    settings: Settings,
    sessions: Callable[[], Session],
    viewer: Viewer | None = None,
) -> Loaded:
    settings = limits_service.effective_settings(db, settings, ws_id)
    loader = _Tracking(DbSourceLoader(sessions, ws_id, settings, viewer))
    max_rows = settings.flow_max_rows
    slot = flows._semaphore(settings.flow_max_concurrent_runs)  # noqa: SLF001
    if isinstance(source, CrmRef):
        _take(slot)
        try:
            df = _call_with_budget(
                lambda: loader.load(CrmSource(table=source.table), max_rows), TIME_BUDGET_S, slot
            )
        except SourceError as exc:
            raise InvalidInputError(str(exc)) from None
        assert isinstance(df, pd.DataFrame)
        return Loaded(df, loader.capped)

    row = flows.require_flow(db, ws_id, source.flow_id)  # another workspace's flow: 404
    graph = flows.parse_stored(row.graph)
    if source.node_id not in {n.id for n in graph.nodes}:
        raise InvalidInputError("the block does not exist in this flow")
    _take(slot)
    limits = FlowLimits(
        max_rows=max_rows, timeout_s=min(settings.flow_run_timeout_s, TIME_BUDGET_S * 2)
    )
    captured: dict[str, pd.DataFrame] = {}
    models = flows.resolve_models(db, ws_id, graph)  # saved models for `score` blocks
    gates = gate_config_from_settings(settings)

    def run() -> dict:
        from app.flows.engine import run_graph

        return run_graph(
            graph, loader, gates, limits, source.node_id, capture=captured, models=models
        )  # type: ignore[arg-type]

    try:
        results = flows.run_in_thread(run, limits.timeout_s + 5, slot)
    except flows.RunTimeout as exc:
        raise InvalidInputError(str(exc)) from None
    res = results.get(source.node_id)
    if res is None or res.status != "ok":
        why = res.error if res is not None and res.error else "an upstream block failed"
        raise InvalidInputError(f"the block could not run: {why}")
    df = captured.get(source.node_id)
    if df is None:
        raise InvalidInputError("this block has no table output to visualize")
    return Loaded(df, loader.capped)


def truncation_note(n_rows: int) -> str:
    return f"computed on the first {n_rows:,} rows (the source is capped)"
