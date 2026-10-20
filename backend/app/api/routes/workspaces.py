"""Workspaces and their users."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentViewer, CurrentWorkspace, Db, SessionUser, SuperAdmin
from app.api.schemas import UserCreate, UserOut, WorkspaceCreate, WorkspaceOut
from app.auth.visibility import require_admin
from app.db.models import Membership, Workspace
from app.domain.schemas import UserIn
from app.services import user_accounts, users, workspaces

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


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201, tags=["workspaces"])
def create_workspace(body: WorkspaceCreate, db: Db, admin: SuperAdmin) -> WorkspaceOut:
    ws = workspaces.create_workspace(db, body.slug, body.name, is_demo=False)
    user_accounts.add_membership(db, admin, ws, role="admin")
    db.commit()
    return _out(ws)


@router.get("/w/{ws}/users", response_model=list[UserOut], tags=["workspaces"])
def list_users(db: Db, ws: CurrentWorkspace) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in users.list_users(db, ws.id)]


@router.post("/w/{ws}/users", response_model=UserOut, status_code=201, tags=["workspaces"])
def create_user(body: UserCreate, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer) -> UserOut:
    require_admin(viewer)
    user = users.create_user(db, ws.id, UserIn(**body.model_dump()))
    db.commit()
    return UserOut.model_validate(user)
