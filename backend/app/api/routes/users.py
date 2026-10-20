"""Members of a workspace: who may sign in, with which role (workspace admin only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app.api.deps import AdminViewer, AppSettings, CurrentWorkspace, Db
from app.api.schemas_auth import MemberCreate, MemberOut, MemberUpdate, PasswordReset
from app.auth import passwords, sessions
from app.auth.access import empty_password_allowed
from app.db.models import Membership, UserAccount
from app.services import user_accounts
from app.services.errors import InvalidInputError, NotFoundError

router = APIRouter(tags=["members"])


def _out(m: Membership, u: UserAccount, app_user_name: str | None) -> MemberOut:
    return MemberOut(
        user_id=u.id,
        email=u.email,
        display_name=u.display_name,
        is_admin=u.is_admin,
        disabled=u.disabled,
        has_password=u.password_hash is not None,
        role="admin" if m.role == "admin" else "rep",
        see_all=m.see_all,
        delete_own=m.delete_own,
        app_user_id=m.app_user_id,
        app_user_name=app_user_name,
        last_login_at=u.last_login_at,
    )


def _one(db: Db, ws_id: uuid.UUID, user_id: uuid.UUID) -> MemberOut:
    for m, u, n in user_accounts.list_members(db, ws_id):
        if u.id == user_id:
            return _out(m, u, n)
    raise NotFoundError("member not found")


def _target(db: Db, ws_id: uuid.UUID, user_id: uuid.UUID) -> tuple[Membership, UserAccount]:
    m = user_accounts.get_membership(db, user_id, ws_id)
    u = db.get(UserAccount, user_id)
    if m is None or u is None:
        raise NotFoundError("member not found")
    return m, u


@router.get("/w/{ws}/members", response_model=list[MemberOut])
def list_members(db: Db, ws: CurrentWorkspace, viewer: AdminViewer) -> list[MemberOut]:
    return [_out(*row) for row in user_accounts.list_members(db, ws.id)]


@router.post("/w/{ws}/members", response_model=MemberOut, status_code=201)
def add_member(
    body: MemberCreate, db: Db, ws: CurrentWorkspace, viewer: AdminViewer, settings: AppSettings
) -> MemberOut:
    user = user_accounts.get_by_email(db, body.email)
    if user is None:
        empty_ok = empty_password_allowed(db, settings, None, extra_workspace_id=ws.id)
        pw_hash = passwords.hash_for_new_password(body.password or "", empty_allowed=empty_ok)
        user = user_accounts.create_account(
            db, body.email, body.display_name or body.email.split("@")[0], pw_hash
        )
    elif user.password_hash is None and not empty_password_allowed(
        db, settings, user, extra_workspace_id=ws.id
    ):
        raise InvalidInputError(
            "this account has an empty password; reset it before adding it here"
        )
    user_accounts.add_membership(
        db,
        user,
        ws,
        role=body.role,
        see_all=body.see_all,
        delete_own=body.delete_own,
        app_user_id=body.app_user_id,
    )
    db.commit()
    return _one(db, ws.id, user.id)


@router.patch("/w/{ws}/members/{user_id}", response_model=MemberOut)
def update_member(
    user_id: uuid.UUID, body: MemberUpdate, db: Db, ws: CurrentWorkspace, viewer: AdminViewer
) -> MemberOut:
    m, u = _target(db, ws.id, user_id)
    if body.role == "rep" and (u.is_admin or u.id == viewer.user_id):
        raise HTTPException(status_code=403, detail="you cannot remove your own admin rights")
    if body.role is not None:
        m.role = body.role
    if body.see_all is not None:
        m.see_all = body.see_all
    if body.delete_own is not None:
        m.delete_own = body.delete_own
    if body.display_name is not None:
        u.display_name = body.display_name
    if body.clear_app_user:
        m.app_user_id = None
    elif body.app_user_id is not None and body.app_user_id != m.app_user_id:
        user_accounts.check_app_user(db, ws.id, body.app_user_id)
        m.app_user_id = body.app_user_id
    db.commit()
    return _one(db, ws.id, user_id)


@router.post("/w/{ws}/members/{user_id}/password", status_code=204)
def reset_password(
    user_id: uuid.UUID,
    body: PasswordReset,
    db: Db,
    ws: CurrentWorkspace,
    viewer: AdminViewer,
    settings: AppSettings,
) -> None:
    _, u = _target(db, ws.id, user_id)
    u.password_hash = passwords.hash_for_new_password(
        body.password, empty_allowed=empty_password_allowed(db, settings, u)
    )
    sessions.end_all_sessions(db, u.id)
    db.commit()


@router.post("/w/{ws}/members/{user_id}/disable", status_code=204)
def disable_member(user_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: AdminViewer) -> None:
    _, u = _target(db, ws.id, user_id)
    if u.is_admin or u.id == viewer.user_id:
        raise HTTPException(status_code=403, detail="you cannot disable this account")
    u.disabled = True
    sessions.end_all_sessions(db, u.id)
    db.commit()


@router.post("/w/{ws}/members/{user_id}/enable", status_code=204)
def enable_member(user_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: AdminViewer) -> None:
    _, u = _target(db, ws.id, user_id)
    u.disabled = False
    db.commit()


@router.delete("/w/{ws}/members/{user_id}", status_code=204)
def remove_member(user_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: AdminViewer) -> None:
    m, u = _target(db, ws.id, user_id)
    if u.is_admin or u.id == viewer.user_id:
        raise HTTPException(status_code=403, detail="you cannot remove this member")
    db.delete(m)
    db.commit()
