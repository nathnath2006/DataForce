"""Flow CRUD, the block catalog and the run endpoint (docs/M2A-CONTRACT.md section 4)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import AppSettings, CurrentWorkspace, Db
from app.api.errors import error_response
from app.api.schemas_flows import (
    BlockPorts,
    Catalog,
    FlowCreate,
    FlowOut,
    FlowSummary,
    FlowUpdate,
)
from app.db.models import Flow
from app.db.session import SessionLocal
from app.flows.schemas import PORTS, ColumnInfo, RunRequest, RunResponse
from app.flows.sources.crm import CRM_COLUMNS
from app.flows.sources.loader import DbSourceLoader
from app.services import flows
from app.stats.engine import gate_config_from_settings

router = APIRouter(tags=["flows"])


def get_loader_session_factory() -> Callable[[], Session]:
    """The sessions the flow worker thread opens (its own, closed per read). Tests override it."""
    return SessionLocal


LoaderSessions = Annotated[Callable[[], Session], Depends(get_loader_session_factory)]


def _out(row: Flow) -> FlowOut:
    return FlowOut(
        id=row.id,
        name=row.name,
        description=row.description,
        graph=flows.parse_stored(row.graph),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/w/{ws}/flows", response_model=list[FlowSummary])
def list_flows(db: Db, ws: CurrentWorkspace) -> list[FlowSummary]:
    return [
        FlowSummary(
            id=f.id,
            name=f.name,
            description=f.description,
            n_nodes=flows.n_nodes(f.graph),
            updated_at=f.updated_at,
        )
        for f in flows.list_flows(db, ws.id)
    ]


@router.post("/w/{ws}/flows", response_model=FlowOut, status_code=201)
def create_flow(body: FlowCreate, db: Db, ws: CurrentWorkspace) -> FlowOut:
    row = flows.create_flow(db, ws.id, body.name, body.description, body.graph)
    db.commit()
    return _out(row)


# Fixed paths before /flows/{flow_id}.
@router.get("/w/{ws}/flows/catalog", response_model=Catalog)
def catalog(ws: CurrentWorkspace) -> Catalog:
    return Catalog(
        blocks={t: BlockPorts(inputs=list(i), outputs=list(o)) for t, (i, o) in PORTS.items()},
        crm_tables={
            table: [ColumnInfo(name=n, dtype=d) for n, d in cols]  # type: ignore[arg-type]
            for table, cols in CRM_COLUMNS.items()
        },
    )


@router.post("/w/{ws}/flows/run", response_model=RunResponse)
def run_flow(
    body: RunRequest,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    sessions: LoaderSessions,
) -> Any:
    """Runs the graph the editor sends (saved or not). The engine runs in a worker thread that
    reads through its own short-lived sessions; this request's session only records the run."""
    loader = DbSourceLoader(sessions, ws.id, settings)
    try:
        run_id, started_at, results = flows.execute(
            db,
            ws.id,
            body.graph,
            body.target,
            loader,
            gate_config_from_settings(settings),
            settings,
        )
    except flows.TooManyRuns as exc:
        return error_response(409, "conflict", str(exc))
    except flows.RunTimeout as exc:
        return error_response(504, "timeout", str(exc))
    return RunResponse(run_id=run_id, started_at=started_at, results=results)


@router.get("/w/{ws}/flows/{flow_id}", response_model=FlowOut)
def get_flow(flow_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> FlowOut:
    return _out(flows.require_flow(db, ws.id, flow_id))


@router.put("/w/{ws}/flows/{flow_id}", response_model=FlowOut)
def update_flow(flow_id: uuid.UUID, body: FlowUpdate, db: Db, ws: CurrentWorkspace) -> FlowOut:
    row = flows.update_flow(db, ws.id, flow_id, body.model_dump(exclude_unset=True) | _graph(body))
    db.commit()
    return _out(row)


def _graph(body: FlowUpdate) -> dict[str, Any]:
    # model_dump turned the graph into a dict; the service wants the validated model
    return {"graph": body.graph} if "graph" in body.model_fields_set else {}


@router.delete("/w/{ws}/flows/{flow_id}", status_code=204)
def delete_flow(flow_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> Response:
    flows.delete_flow(db, ws.id, flow_id)
    db.commit()
    return Response(status_code=204)
