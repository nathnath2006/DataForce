"""Data quality counts (read-only)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentViewer, CurrentWorkspace, Db
from app.api.schemas_quality import QualityOut
from app.services import quality

router = APIRouter(tags=["quality"])


@router.get("/w/{ws}/quality", response_model=QualityOut)
def get_quality(db: Db, ws: CurrentWorkspace, viewer: CurrentViewer) -> QualityOut:
    return quality.quality_report(db, ws.id, viewer)
