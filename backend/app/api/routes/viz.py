"""Viz query, field listing and Explain (M4). Aggregates are exact (pandas), capped and timed."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AppSettings, CurrentViewer, CurrentWorkspace, Db
from app.api.routes.flows import LoaderSessions
from app.api.schemas_viz import (
    ExplainRequest,
    ExplainResponse,
    FieldsRequest,
    FieldsResponse,
    QueryRequest,
    QueryResponse,
)
from app.flows.blocks._common import dtype_of
from app.flows.ports import FlowLimits
from app.flows.schemas import ColumnInfo
from app.services import limits as limits_service
from app.stats.engine import gate_config_from_settings
from app.viz import engine, explain
from app.viz import source as src

router = APIRouter(tags=["viz"])


@router.post("/w/{ws}/viz/fields", response_model=FieldsResponse)
def fields(
    body: FieldsRequest,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    sessions: LoaderSessions,
    viewer: CurrentViewer,
) -> FieldsResponse:
    loaded = src.load(db, ws.id, body.source, settings, sessions, viewer)
    df = loaded.df
    cols = [
        ColumnInfo(name=str(c), dtype=dtype_of(df.iloc[:, i]))  # type: ignore[arg-type]
        for i, c in enumerate(df.columns)
    ]
    notes = [src.truncation_note(len(df))] if loaded.truncated else []
    return FieldsResponse(
        columns=cols, n_source_rows=len(df), truncated_source=loaded.truncated, notes=notes
    )


@router.post("/w/{ws}/viz/query", response_model=QueryResponse)
def query(
    body: QueryRequest,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    sessions: LoaderSessions,
    viewer: CurrentViewer,
) -> QueryResponse:
    loaded = src.load(db, ws.id, body.source, settings, sessions, viewer)
    result, n_filtered, n_groups, notes = engine.run(loaded.df, body)
    if loaded.truncated:
        notes = [src.truncation_note(len(loaded.df)), *notes]
    cols, rows = engine.to_rows(result)
    return QueryResponse(
        columns=cols,  # type: ignore[arg-type]
        rows=rows,
        n_source_rows=len(loaded.df),
        n_filtered_rows=n_filtered,
        n_groups=n_groups,
        truncated_source=loaded.truncated,
        notes=notes,
    )


@router.post("/w/{ws}/viz/explain", response_model=ExplainResponse)
def explain_route(
    body: ExplainRequest,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    sessions: LoaderSessions,
    viewer: CurrentViewer,
) -> ExplainResponse:
    loaded = src.load(db, ws.id, body.source, settings, sessions, viewer)
    df = engine.apply_filters(loaded.df, body.filters)
    eff = limits_service.effective_settings(db, settings, ws.id)
    limits = FlowLimits(max_rows=eff.flow_max_rows, timeout_s=src.TIME_BUDGET_S)
    findings, method, notes = explain.explain(df, body, gate_config_from_settings(settings), limits)
    verified, not_verified = explain.split_sorted(findings)
    if loaded.truncated:
        notes = [src.truncation_note(len(loaded.df)), *notes]
    return ExplainResponse(
        measure=body.measure,
        method=method,
        n_rows=len(df),
        truncated_source=loaded.truncated,
        verified=verified,
        not_verified=not_verified,
        notes=notes,
    )
