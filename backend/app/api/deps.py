"""FastAPI dependencies shared by every router (contract: owned by the tech lead).

Transactions: `get_db` yields a session and ALWAYS rolls back what was not committed, then
closes it. A route that changes data calls `db.commit()` itself before building its response,
so a failed commit is an error response, never a 200 for data that was not saved.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import SLUG_PATTERN
from app.auth.viewer import Viewer
from app.config import Settings, get_settings
from app.db.models import Membership, UserAccount, Workspace
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


def _access(db: Session, request: Request, slug: str) -> tuple[Workspace, Viewer]:
    """The workspace and the signed-in user's viewer in it. A non-member gets the same 404 as a
    missing workspace (no enumeration); a superadmin without membership is an admin."""
    cached = getattr(request.state, "access", None)
    if cached is not None and cached[0].slug == slug:
        return cached
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="sign in required")
    ws = workspaces.get_workspace_by_slug(db, slug)
    user = db.get(UserAccount, user_id)
    if ws is None or user is None:
        raise NotFoundError("workspace not found")
    member = db.scalars(
        select(Membership).where(
            Membership.user_account_id == user.id, Membership.workspace_id == ws.id
        )
    ).one_or_none()
    if member is not None:
        viewer = Viewer(
            workspace_id=ws.id,
            user_id=user.id,
            app_user_id=member.app_user_id,
            role="admin" if member.role == "admin" else "rep",
            see_all=member.see_all,
            delete_own=member.delete_own,
            is_superadmin=user.is_admin,
        )
    elif user.is_admin:
        viewer = Viewer(
            workspace_id=ws.id,
            user_id=user.id,
            app_user_id=None,
            role="admin",
            is_superadmin=True,
        )
    else:
        raise NotFoundError("workspace not found")
    request.state.access = (ws, viewer)
    return ws, viewer


def get_workspace(
    db: Db, request: Request, ws: Annotated[str, Path(pattern=SLUG_PATTERN)]
) -> Workspace:
    return _access(db, request, ws)[0]


CurrentWorkspace = Annotated[Workspace, Depends(get_workspace)]


def get_viewer(request: Request, db: Db, ws: CurrentWorkspace) -> Viewer:
    return _access(db, request, ws.slug)[1]


CurrentViewer = Annotated[Viewer, Depends(get_viewer)]


def get_session_user(request: Request, db: Db) -> UserAccount:
    user_id = getattr(request.state, "user_id", None)
    user = db.get(UserAccount, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(status_code=401, detail="sign in required")
    return user


SessionUser = Annotated[UserAccount, Depends(get_session_user)]


def require_superadmin(user: SessionUser) -> UserAccount:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="administrator only")
    return user


SuperAdmin = Annotated[UserAccount, Depends(require_superadmin)]


def require_admin(viewer: CurrentViewer) -> Viewer:
    """Admin of this workspace (workspace admin role or superadmin); a rep gets 403."""
    if not viewer.is_admin:
        raise HTTPException(status_code=403, detail="administrator only")
    return viewer


AdminViewer = Annotated[Viewer, Depends(require_admin)]
