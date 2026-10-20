"""Workspaces and their users."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select, update

from app.api.deps import (
    AppSettings,
    CurrentViewer,
    CurrentWorkspace,
    Db,
    SessionFactory,
    SessionUser,
    SuperAdmin,
)
from app.api.schemas import UserCreate, UserOut, WorkspaceCreate, WorkspaceOut, WorkspaceSetup
from app.auth.visibility import require_admin
from app.db.models import Membership, UserAccount, Workspace
from app.domain.schemas import UserIn
from app.services import limits as limits_service
from app.services import user_accounts, users, workspace_setup, workspaces
from app.services.admin import db_size
from app.services.errors import ForbiddenError, NotFoundError

router = APIRouter()


def _out(ws: Workspace, n_accounts: int = 0, n_contacts: int = 0, n_deals: int = 0) -> WorkspaceOut:
    return WorkspaceOut(
        slug=ws.slug,
        name=ws.name,
        is_demo=ws.is_demo,
        created_at=ws.created_at,
        n_accounts=n_accounts,
        n_contacts=n_contacts,
        n_deals=n_deals,
        setup_state="preparing" if ws.setup_state == "preparing" else "ready",
    )


@router.get("/workspaces", response_model=list[WorkspaceOut], tags=["workspaces"])
def list_workspaces(db: Db, user: SessionUser) -> list[WorkspaceOut]:
    rows = workspaces.list_workspaces_with_counts(db)
    if not user.is_admin:  # a member sees only their own workspaces
        mine = set(
            db.scalars(select(Membership.workspace_id).where(Membership.user_account_id == user.id))
        )
        rows = [r for r in rows if r[0].id in mine]
    return [_out(*row) for row in rows]


QUOTA_STOP_PCT = 80  # no new test workspace when the database is this full


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201, tags=["workspaces"])
def create_workspace(
    body: WorkspaceCreate,
    db: Db,
    user: SessionUser,
    settings: AppSettings,
    factory: SessionFactory,
) -> WorkspaceOut:
    """A superadmin, or an account with workspace credits (one is taken). The creator is admin."""
    if not user.is_admin:
        # One atomic decrement: two requests cannot spend the same credit.
        spent = db.execute(
            update(UserAccount)
            .where(UserAccount.id == user.id, UserAccount.workspace_credits > 0)
            .values(workspace_credits=UserAccount.workspace_credits - 1)
            .returning(UserAccount.id)
        ).first()
        if spent is None:
            raise ForbiddenError("You cannot create a workspace.")
    admin = user
    if body.kind == "real":
        ws = workspaces.create_workspace(db, body.slug, body.name, is_demo=False)
        user_accounts.add_membership(db, admin, ws, role="admin")
        db.commit()
        return _out(ws)
    quota = limits_service.effective(db, settings, "db_quota_mb", None)
    used = db_size(db, quota)["used_pct"]
    if used is not None and used > QUOTA_STOP_PCT:
        raise HTTPException(
            status_code=409,
            detail=f"The database is {used:.0f}% full; a test workspace would not fit.",
        )
    if not workspace_setup.reserve(body.slug):
        raise HTTPException(
            status_code=409, detail="A test workspace is already being prepared. Please wait."
        )
    try:
        ws = workspaces.create_workspace(db, body.slug, body.name, is_demo=True)
        ws.setup_state = "preparing"
        user_accounts.add_membership(db, admin, ws, role="admin")
        db.commit()
    except BaseException:
        workspace_setup.release(body.slug)
        raise
    out = _out(ws)
    workspace_setup.start(body.slug, factory)
    return out


@router.get("/workspaces/{slug}/setup", response_model=WorkspaceSetup, tags=["workspaces"])
def workspace_setup_status(slug: str, db: Db, user: SessionUser) -> WorkspaceSetup:
    ws = workspaces.get_workspace_by_slug(db, slug)
    if not user.is_admin:  # the admin of a workspace they created may watch it fill
        member = ws and user_accounts.get_membership(db, user.id, ws.id)
        if member is None or member.role != "admin":
            raise ForbiddenError("administrator only")
    job = workspace_setup.get(slug)
    total = workspace_setup.TOTAL
    # A ready row wins over a stale failed entry (the slug may have been reused within 10 min).
    if ws is not None and ws.setup_state is None:
        return WorkspaceSetup(state="ready", step=None, done=total, total=total, error=None)
    if job is not None and job.state == "failed":
        return WorkspaceSetup(state="failed", step=None, done=0, total=total, error=job.error)
    if ws is None:
        raise NotFoundError("workspace not found")
    if job is None:
        return WorkspaceSetup(state="interrupted", step=None, done=0, total=total, error=None)
    return WorkspaceSetup(state="preparing", step=job.step, done=job.done, total=total, error=None)


@router.delete("/workspaces/{slug}", status_code=204, tags=["workspaces"])
def delete_workspace(slug: str, db: Db, admin: SuperAdmin) -> Response:
    ws = workspaces.get_workspace_by_slug(db, slug)
    if ws is None:
        raise NotFoundError("workspace not found")
    if not ws.is_demo:
        raise ForbiddenError("Only a test workspace can be removed here.")
    if workspace_setup.is_running(slug):
        raise HTTPException(status_code=409, detail="This workspace is still being prepared.")
    workspaces.delete_workspace(db, slug)
    db.commit()
    return Response(status_code=204)


@router.get("/w/{ws}/users", response_model=list[UserOut], tags=["workspaces"])
def list_users(db: Db, ws: CurrentWorkspace) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in users.list_users(db, ws.id)]


@router.post("/w/{ws}/users", response_model=UserOut, status_code=201, tags=["workspaces"])
def create_user(body: UserCreate, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer) -> UserOut:
    require_admin(viewer)
    user = users.create_user(db, ws.id, UserIn(**body.model_dump()))
    db.commit()
    return UserOut.model_validate(user)
