"""Saved models: the server re-runs the flow up to a model block and keeps its own parameters.

Nothing the client sends is stored: only the flow id, the block id and a name. Parameters are
plain JSON (never pickle). Scores inherit the saved model's status.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas_viz import CrmRef, FlowRef
from app.auth import visibility
from app.auth.viewer import Viewer
from app.config import Settings
from app.db.models import SavedModel
from app.flows.blocks._common import jsonable
from app.flows.ports import FlowLimits
from app.flows.schemas import ClusterConfig, ModelConfig, NodeResult
from app.flows.scoring import ModelSnapshot, ScoreResult, ScoringError, score_frame
from app.services import flows
from app.services._common import get_scoped
from app.services.errors import InvalidInputError, NotFoundError
from app.stats.engine import gate_config_from_settings
from app.viz import source as viz_source

MAX_MODELS_PER_WORKSPACE = 200
MAX_PARAMS_BYTES = 8_000_000  # serialised parameters (an RBF model keeps its support vectors)
PREVIEW_ROWS = 200
KINDS = {
    "linear_regression": "linear",
    "logistic_regression": "logistic",
    "svm": "svm",
    "svr": "svr",
}
NOT_VERIFIED_NOTE = (
    "This model did not beat its baseline on held-out data, so these scores are not verified."
)
EXPLORATORY_NOTE = "Cluster assignments describe the data; they are exploratory, not verified."


def _node_result(
    db: Session,
    ws_id: uuid.UUID,
    flow_id: uuid.UUID,
    node_id: str,
    settings: Settings,
    sessions: Callable[[], Session],
    viewer: Viewer | None = None,
) -> tuple[Any, NodeResult]:
    """Re-run the flow up to `node_id` in the flows slot. Returns (node config, its result)."""
    from app.flows.engine import run_graph
    from app.flows.sources.loader import DbSourceLoader

    row = flows.require_flow(db, ws_id, flow_id)
    graph = flows.parse_stored(row.graph)
    node = next((n for n in graph.nodes if n.id == node_id), None)
    if node is None:
        raise InvalidInputError("the block does not exist in this flow")
    if not isinstance(node.config, ModelConfig | ClusterConfig):
        raise InvalidInputError("only a model or cluster block can be saved")
    slot = flows._semaphore(settings.flow_max_concurrent_runs)  # noqa: SLF001
    if not slot.acquire(timeout=viz_source.SLOT_WAIT_S):
        raise InvalidInputError("another analysis is still running, try again in a moment")
    limits = FlowLimits(max_rows=settings.flow_max_rows, timeout_s=settings.flow_run_timeout_s)
    loader = DbSourceLoader(sessions, ws_id, settings, viewer)
    gates = gate_config_from_settings(settings)
    models = flows.resolve_models(db, ws_id, graph)
    try:
        results = flows.run_in_thread(
            lambda: run_graph(graph, loader, gates, limits, node_id, models=models),
            limits.timeout_s + 5,
            slot,
        )
    except flows.RunTimeout as exc:
        raise InvalidInputError(str(exc)) from None
    res = results.get(node_id)
    if res is None or res.status != "ok":
        why = res.error if res is not None and res.error else "an upstream block failed"
        raise InvalidInputError(f"the block could not run, so nothing was saved: {why}")
    return node.config, res


def save_model(
    db: Session,
    ws_id: uuid.UUID,
    flow_id: uuid.UUID,
    node_id: str,
    name: str,
    settings: Settings,
    sessions: Callable[[], Session],
    viewer: Viewer | None = None,
) -> SavedModel:
    n = db.scalar(
        select(func.count()).select_from(SavedModel).where(SavedModel.workspace_id == ws_id)
    )
    if (n or 0) >= MAX_MODELS_PER_WORKSPACE:
        raise InvalidInputError(f"at most {MAX_MODELS_PER_WORKSPACE} saved models per workspace")
    cfg, res = _node_result(db, ws_id, flow_id, node_id, settings, sessions, viewer)
    params = res.model_params
    view = res.view
    if params is None or view is None:
        raise InvalidInputError("this block produced no model parameters")
    if isinstance(cfg, ClusterConfig):
        kind = "kmeans"
        features = [str(f) for f in cfg.features]
        status = "exploratory"
    else:
        kind = KINDS[cfg.kind]
        spec = params["features"]
        features = [f["name"] for f in spec["numeric"]] + [f["name"] for f in spec["categorical"]]
        status = view.status  # type: ignore[union-attr]
        if params.get("exportable") is False:
            raise InvalidInputError(
                "this RBF model has too many support vectors to be saved: use a linear kernel "
                "or fewer training rows"
            )
        if params.get("kernel") == "rbf" and "support_vectors" not in params:
            raise InvalidInputError("this model's parameters cannot be exported")
    try:
        size = len(json.dumps(params, allow_nan=False))
    except ValueError:  # NaN or infinity: JSONB would refuse it
        raise InvalidInputError("the model's parameters contain non-finite numbers") from None
    if size > MAX_PARAMS_BYTES:
        raise InvalidInputError("the model's parameters are too large to save")
    metrics = {
        "metrics": [m.model_dump(mode="json") for m in view.metrics],  # type: ignore[union-attr]
        "n_train": getattr(view, "n_train", None),
        "n_test": getattr(view, "n_test", None),
        "reasons": list(getattr(view, "reasons", [])),
        "caveats": list(getattr(view, "caveats", [])),
        "confusion": getattr(view, "confusion", None),
    }
    row = SavedModel(
        workspace_id=ws_id,
        name=name,
        flow_id=flow_id,
        node_id=node_id,
        kind=kind,
        params=params,
        features=features,
        metrics=metrics,
        status=status,
        created_by_id=viewer.app_user_id if viewer is not None else None,
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return row


def list_models(db: Session, ws_id: uuid.UUID) -> list[SavedModel]:
    stmt = (
        select(SavedModel)
        .where(SavedModel.workspace_id == ws_id)
        .order_by(SavedModel.created_at.desc(), SavedModel.id)
        .limit(MAX_MODELS_PER_WORKSPACE)
    )
    return list(db.scalars(stmt))


def require_model(db: Session, ws_id: uuid.UUID, model_id: uuid.UUID) -> SavedModel:
    row = get_scoped(db, SavedModel, ws_id, model_id)
    if row is None:
        raise NotFoundError("model not found")
    return row


def rename_model(db: Session, ws_id: uuid.UUID, model_id: uuid.UUID, name: str) -> SavedModel:
    row = require_model(db, ws_id, model_id)
    row.name = name
    db.flush()
    db.refresh(row)
    return row


def delete_model(
    db: Session, ws_id: uuid.UUID, model_id: uuid.UUID, viewer: Viewer | None = None
) -> None:
    row = require_model(db, ws_id, model_id)
    if viewer is not None:
        visibility.require_delete(viewer, row.created_by_id)
    db.delete(row)
    db.flush()


def score_source(
    db: Session,
    ws_id: uuid.UUID,
    model_id: uuid.UUID,
    source: CrmRef | FlowRef,
    settings: Settings,
    sessions: Callable[[], Session],
    viewer: Viewer | None = None,
) -> dict[str, Any]:
    row = require_model(db, ws_id, model_id)
    snap = ModelSnapshot(
        id=str(row.id),
        name=row.name,
        kind=row.kind,
        params=row.params,
        features=[str(f) for f in row.features],
        status=row.status,
    )
    loaded = viz_source.load(db, ws_id, source, settings, sessions, viewer)
    # scoring (an RBF model: rows x 2,000 support vectors) runs in an analysis slot and budget too
    slot = flows._semaphore(settings.flow_max_concurrent_runs)  # noqa: SLF001
    viz_source._take(slot)  # noqa: SLF001
    try:
        res = viz_source._call_with_budget(  # noqa: SLF001
            lambda: score_frame(snap, loaded.df), viz_source.TIME_BUDGET_S, slot
        )
    except ScoringError as exc:
        raise InvalidInputError(str(exc)) from None
    assert isinstance(res, ScoreResult)
    sc = res.columns
    notes = list(res.notes)
    if loaded.truncated:
        notes.insert(0, viz_source.truncation_note(len(loaded.df)))
    first = pd.concat([loaded.df.head(PREVIEW_ROWS), sc.head(PREVIEW_ROWS)], axis=1)
    cols = [str(c) for c in first.columns]
    rows = [
        {c: jsonable(v) for c, v in zip(cols, r, strict=True)}
        for r in first.itertuples(index=False)
    ]
    s = sc["score"].dropna()
    if row.kind == "kmeans":
        summary = {
            "count": int(len(s)),
            "class_counts": {str(int(k)): int(v) for k, v in s.value_counts().sort_index().items()},
        }
    else:
        summary = {
            "count": int(len(s)),
            "mean": jsonable(s.mean()) if len(s) else None,
            "min": jsonable(s.min()) if len(s) else None,
            "max": jsonable(s.max()) if len(s) else None,
        }
        if "score_class" in sc:
            summary["class_counts"] = {
                ("positive" if k else "negative"): int(v)
                for k, v in sc["score_class"].value_counts().items()
            }
    note = (
        NOT_VERIFIED_NOTE
        if row.status == "not_verified"
        else EXPLORATORY_NOTE
        if row.status == "exploratory"
        else None
    )
    return {
        "model_id": row.id,
        "model_kind": row.kind,
        "status": row.status,
        "status_note": note,
        "n_rows": len(loaded.df),
        "n_scored": int(len(s)),
        "n_imputed": res.n_imputed,
        "summary": summary,
        "columns": cols,
        "rows": rows,
        "truncated_source": loaded.truncated,
        "notes": notes,
    }
