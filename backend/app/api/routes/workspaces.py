"""Workspaces and their users."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentWorkspace, Db
from app.api.schemas import UserCreate, UserOut, WorkspaceCreate, WorkspaceOut
from app.db.models import Workspace
from app.domain.schemas import UserIn
from app.services import users, workspaces

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
def list_workspaces(db: Db) -> list[WorkspaceOut]:
    return [_out(*row) for row in workspaces.list_workspaces_with_counts(db)]


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201, tags=["workspaces"])
def create_workspace(body: WorkspaceCreate, db: Db) -> WorkspaceOut:
    ws = workspaces.create_workspace(db, body.slug, body.name, is_demo=False)
    db.commit()
    return _out(ws)


@router.get("/w/{ws}/users", response_model=list[UserOut], tags=["workspaces"])
def list_users(db: Db, ws: CurrentWorkspace) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in users.list_users(db, ws.id)]


@router.post("/w/{ws}/users", response_model=UserOut, status_code=201, tags=["workspaces"])
def create_user(body: UserCreate, db: Db, ws: CurrentWorkspace) -> UserOut:
    user = users.create_user(db, ws.id, UserIn(**body.model_dump()))
    db.commit()
    return UserOut.model_validate(user)
