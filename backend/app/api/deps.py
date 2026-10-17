"""FastAPI dependencies shared by every router (contract: owned by the tech lead).

Transactions: `get_db` yields a session and ALWAYS rolls back what was not committed, then
closes it. A route that changes data calls `db.commit()` itself before building its response,
so a failed commit is an error response, never a 200 for data that was not saved.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Path, Request
from sqlalchemy.orm import Session

from app.api.schemas import SLUG_PATTERN
from app.config import Settings, get_settings
from app.db.models import Workspace
from app.db.session import SessionLocal
from app.services import workspaces
from app.services.errors import NotFoundError


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def get_app_settings(request: Request) -> Settings:
    """The settings the app was built with (`dataforce ui --port` adjusts them), so a route never
    disagrees with the server it runs in (e.g. the OAuth redirect URI's port)."""
    settings = getattr(request.app.state, "settings", None)
    return settings if isinstance(settings, Settings) else get_settings()


Db = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]


def get_workspace(db: Db, ws: Annotated[str, Path(pattern=SLUG_PATTERN)]) -> Workspace:
    found = workspaces.get_workspace_by_slug(db, ws)
    if found is None:
        raise NotFoundError("workspace not found")
    return found


CurrentWorkspace = Annotated[Workspace, Depends(get_workspace)]
