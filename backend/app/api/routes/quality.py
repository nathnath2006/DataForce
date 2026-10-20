"""Data quality counts (read-only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentViewer, CurrentWorkspace, Db
from app.api.schemas_quality import QualityOut
from app.auth import visibility
from app.services import quality

router = APIRouter(tags=["quality"])


@router.get("/w/{ws}/quality", response_model=QualityOut)
def get_quality(
    db: Db, ws: CurrentWorkspace, viewer: CurrentViewer, owner: uuid.UUID | None = None
) -> QualityOut:
    """`owner` (a CRM user id): that rep's rows; admin and see-all members only (else 403)."""
    return quality.quality_report(db, ws.id, visibility.scoped_viewer(db, viewer, owner))
