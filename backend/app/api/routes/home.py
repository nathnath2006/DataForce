"""Home dashboard: the signed-in member's numbers (or one rep's, for the admin)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentViewer, CurrentWorkspace, Db
from app.api.schemas_home import HomeOut
from app.services import home as home_service

router = APIRouter(tags=["home"])


@router.get("/w/{ws}/home", response_model=HomeOut)
def get_home(
    db: Db, ws: CurrentWorkspace, viewer: CurrentViewer, owner: uuid.UUID | None = None
) -> HomeOut:
    """`owner` (a CRM user id): that rep's numbers; admin and see-all members only (else 403)."""
    return home_service.home(db, ws.id, viewer, owner)
