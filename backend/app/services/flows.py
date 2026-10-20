"""Saved analysis flows and flow execution (docs/M2A-CONTRACT.md sections 3 and 4)."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Flow, SavedModel
from app.domain.enums import RunKind, RunStatus
from app.domain.schemas import GateConfig
from app.flows.ports import FlowLimits, SourceLoader
from app.flows.schemas import FlowGraph, NodeResult, ScoreConfig
from app.flows.scoring import ModelSnapshot
from app.services import limits as limits_service
from app.services import runs
from app.services._common import get_scoped
from app.services.errors import InvalidInputError, NotFoundError


class RunTimeout(Exception):
    """The engine did not answer within the run timeout."""


class TooManyRuns(Exception):
    """Every run slot of this process is taken."""


_slots_lock = threading.Lock()
_slots: threading.BoundedSemaphore | None = None
_slots_size = 0


def _semaphore(size: int) -> threading.BoundedSemaphore:
    global _slots, _slots_size
    with _slots_lock:
        if _slots is None or _slots_size != size:
            _slots, _slots_size = threading.BoundedSemaphore(size), size
        return _slots


def dump_graph(graph: FlowGraph) -> dict[str, Any]:
    return graph.model_dump(mode="json", by_alias=True)  # by_alias: Aggregation.alias is "as"


def parse_stored(raw: dict[str, Any] | None) -> FlowGraph:
    return FlowGraph.model_validate(raw or {})


def n_nodes(raw: dict[str, Any] | None) -> int:
    return len((raw or {}).get("nodes", []))


def list_flows(db: Session, ws_id: uuid.UUID) -> list[Flow]:
    stmt = select(Flow).where(Flow.workspace_id == ws_id).order_by(Flow.updated_at.desc(), Flow.id)
    return list(db.scalars(stmt))


def require_flow(db: Session, ws_id: uuid.UUID, flow_id: uuid.UUID) -> Flow:
    row = get_scoped(db, Flow, ws_id, flow_id)
    if row is None:
        raise NotFoundError("flow not found")
    return row


def create_flow(
    db: Session, ws_id: uuid.UUID, name: str, description: str | None, graph: FlowGraph
) -> Flow:
    row = Flow(workspace_id=ws_id, name=name, description=description, graph=dump_graph(graph))
    db.add(row)
    db.flush()
    db.refresh(row)
    return row


def update_flow(db: Session, ws_id: uuid.UUID, flow_id: uuid.UUID, changes: dict[str, Any]) -> Flow:
    row = require_flow(db, ws_id, flow_id)
    if "name" in changes:
        if changes["name"] is None:
            raise InvalidInputError("name cannot be empty")
        row.name = changes["name"]
    if "description" in changes:
        row.description = changes["description"]
    if changes.get("graph") is not None:
        row.graph = dump_graph(changes["graph"])
    db.flush()
    db.refresh(row)
    return row


def delete_flow(db: Session, ws_id: uuid.UUID, flow_id: uuid.UUID) -> None:
    db.delete(require_flow(db, ws_id, flow_id))
    db.flush()


# --- execution ------------------------------------------------------------------------------------
def resolve_models(db: Session, ws_id: uuid.UUID, graph: FlowGraph) -> dict[str, ModelSnapshot]:
    """The saved models that `score` blocks of the graph use, read once when a run starts (the
    engine and its worker thread never touch the database for them). Only this workspace's."""
    ids = {n.config.model_id for n in graph.nodes if isinstance(n.config, ScoreConfig)}
    if not ids:
        return {}
    rows = db.scalars(
        select(SavedModel).where(SavedModel.workspace_id == ws_id, SavedModel.id.in_(ids))
    )
    return {
        str(r.id): ModelSnapshot(
            id=str(r.id),
            name=r.name,
            kind=r.kind,
            params=r.params,
            features=[str(f) for f in r.features],
            status=r.status,
        )
        for r in rows
    }


def _engine_run(
    graph: FlowGraph,
    loader: SourceLoader,
    gates: GateConfig,
    limits: FlowLimits,
    target: str | None,
    models: dict[str, ModelSnapshot] | None = None,
) -> dict[str, NodeResult]:
    from app.flows.engine import run_graph  # agent E; imported late so this module loads without it

    return run_graph(graph, loader, gates, limits, target, models=models)


def run_in_thread(
    fn: Callable[[], dict[str, NodeResult]],
    timeout_s: float,
    slot: threading.BoundedSemaphore | None = None,
) -> dict[str, NodeResult]:
    """Run `fn` in a daemon worker thread and wait at most `timeout_s`. A thread cannot be killed:
    on timeout it is abandoned (the engine also checks its own deadline between nodes)."""
    box: dict[str, Any] = {}

    def work() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - reported to the caller
            box["error"] = exc
        finally:
            if slot is not None:  # released when the thread really ends, even after a 504
                slot.release()

    thread = threading.Thread(target=work, name="flow-run", daemon=True)
    try:
        thread.start()
    except BaseException:
        if slot is not None:
            slot.release()
        raise
    thread.join(timeout_s)
    if thread.is_alive():
        raise RunTimeout(f"the flow did not finish within {timeout_s:g} s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def summarise(results: dict[str, NodeResult]) -> dict[str, Any]:
    """What a run row keeps: statuses, row counts and error messages, never data."""
    nodes = {
        node_id: {"status": r.status, "n_rows": r.n_rows, **({"error": r.error} if r.error else {})}
        for node_id, r in results.items()
    }
    counts = {
        s: sum(1 for r in results.values() if r.status == s) for s in ("ok", "error", "skipped")
    }
    return {"counts": counts, "nodes": nodes}


def run_status(results: dict[str, NodeResult]) -> RunStatus:
    errors = sum(1 for r in results.values() if r.status == "error")
    if errors == 0:
        return RunStatus.SUCCEEDED
    return RunStatus.FAILED if errors == len(results) else RunStatus.PARTIAL


def execute(
    db: Session,
    ws_id: uuid.UUID,
    graph: FlowGraph,
    target: str | None,
    loader: SourceLoader,
    gates: GateConfig,
    settings: Settings,
) -> tuple[uuid.UUID, Any, dict[str, NodeResult]]:
    """Record the run, run the engine in a worker thread, close the run. Returns (run id,
    started_at, results)."""
    if target is not None and target not in {n.id for n in graph.nodes}:
        raise InvalidInputError("target is not a node of the graph")
    settings = limits_service.effective_settings(db, settings, ws_id)
    slot = _semaphore(settings.flow_max_concurrent_runs)
    if not slot.acquire(blocking=False):
        raise TooManyRuns("another analysis is still running, try again in a moment")
    try:
        run = runs.start_run(
            db, RunKind.FLOW_RUN, ws_id, {"target": target, "n_nodes": len(graph.nodes)}
        )
        db.commit()  # the row exists even if the request dies; the worker uses other sessions
    except BaseException:
        slot.release()
        raise
    limits = FlowLimits(max_rows=settings.flow_max_rows, timeout_s=settings.flow_run_timeout_s)
    models = resolve_models(db, ws_id, graph)
    try:
        results = run_in_thread(
            lambda: _engine_run(graph, loader, gates, limits, target, models),
            settings.flow_run_timeout_s + 5,
            slot,
        )
    except RunTimeout as exc:
        runs.finish_run(db, run, RunStatus.FAILED, error=str(exc))
        db.commit()
        raise
    except Exception as exc:
        runs.finish_run(db, run, RunStatus.FAILED, error=f"engine failure: {type(exc).__name__}")
        db.commit()
        raise
    runs.finish_run(db, run, run_status(results), result=summarise(results))
    db.commit()
    return run.id, run.started_at, results
