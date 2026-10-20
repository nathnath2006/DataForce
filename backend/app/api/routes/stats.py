"""Pipeline facts (exact SQL) and the verified / not-verified scan."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import or_, select

from app.api.deps import CurrentViewer, CurrentWorkspace, Db
from app.api.schemas import PipelineOut, ScanOut
from app.auth import visibility
from app.auth.viewer import Viewer
from app.db.models import Run
from app.domain.enums import RunKind, RunStatus
from app.domain.schemas import ScanReport
from app.services import analytics
from app.services.errors import NotFoundError

router = APIRouter(tags=["stats"])


def _latest_scan_run(db: Db, ws_id, viewer: Viewer | None = None) -> Run | None:
    """The latest scan over the viewer's rows (scans are scoped: one per rep, or "all")."""
    key = visibility.scope_key(viewer)
    scope = Run.params["scope"].astext
    stmt = (
        select(Run)
        .where(
            Run.workspace_id == ws_id,
            Run.kind == RunKind.STATS_SCAN.value,
            Run.status == RunStatus.SUCCEEDED.value,
            Run.result.is_not(None),
            or_(scope.is_(None), scope == "all") if key == "all" else scope == key,
        )
        .order_by(Run.started_at.desc(), Run.id)
        .limit(1)
    )
    return db.scalars(stmt).first()


@router.get("/w/{ws}/stats/pipeline", response_model=PipelineOut)
def pipeline(db: Db, ws: CurrentWorkspace, viewer: CurrentViewer) -> PipelineOut:
    return PipelineOut.model_validate(analytics.pipeline_summary(db, ws.id, viewer=viewer))


@router.post("/w/{ws}/stats/scan", response_model=ScanOut)
def run_scan(db: Db, ws: CurrentWorkspace, viewer: CurrentViewer) -> ScanOut:
    report = analytics.run_scan(db, ws.id, viewer=viewer)
    run = _latest_scan_run(db, ws.id, viewer)
    db.commit()
    if run is None:  # cannot happen: run_scan just recorded one
        raise NotFoundError("scan run not found")
    return ScanOut(run_id=run.id, report=report)


@router.get("/w/{ws}/stats/scan/latest", response_model=ScanOut)
def latest_scan(db: Db, ws: CurrentWorkspace, viewer: CurrentViewer) -> ScanOut:
    run = _latest_scan_run(db, ws.id, viewer)
    if run is None or run.result is None:
        raise NotFoundError("no scan has been run in this workspace yet")
    return ScanOut(run_id=run.id, report=ScanReport.model_validate(run.result))
