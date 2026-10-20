"""Sign-in accounts and workspace memberships (used by the API and the `users` CLI)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppUser, Membership, UserAccount, Workspace
from app.services.errors import AlreadyExistsError, InvalidInputError, NotFoundError

RESERVED_DOMAIN = "@demo.invalid"  # the public demo's own addresses: nobody can sign up with one


def normalize_email(email: str) -> str:
    value = email.strip().lower()
    if "@" not in value or " " in value or len(value) > 320:
        raise InvalidInputError("enter a valid email address")
    return value


def get_by_email(db: Session, email: str) -> UserAccount | None:
    return db.scalars(
        select(UserAccount).where(UserAccount.email == email.strip().lower())
    ).one_or_none()


def admin_exists(db: Session) -> bool:
    return (
        db.scalars(select(UserAccount.id).where(UserAccount.is_admin.is_(True)).limit(1)).first()
        is not None
    )


def create_account(
    db: Session,
    email: str,
    display_name: str,
    password_hash: str | None,
    *,
    is_admin: bool = False,
    is_demo: bool = False,
) -> UserAccount:
    email = normalize_email(email)
    if email.endswith(RESERVED_DOMAIN) and not is_demo:
        raise InvalidInputError("this email address is reserved")
    name = display_name.strip()
    if not name:
        raise InvalidInputError("the name is empty")
    if get_by_email(db, email) is not None:
        raise AlreadyExistsError("an account with this email already exists")
    user = UserAccount(
        email=email,
        display_name=name,
        password_hash=password_hash,
        is_admin=is_admin,
        is_demo=is_demo,
    )
    db.add(user)
    db.flush()
    return user


def check_app_user(db: Session, ws_id: uuid.UUID, app_user_id: uuid.UUID | None) -> None:
    if app_user_id is None:
        return
    au = db.get(AppUser, app_user_id)
    if au is None or au.workspace_id != ws_id:
        raise NotFoundError("CRM user not found in this workspace")
    taken = db.scalars(
        select(Membership.id).where(
            Membership.workspace_id == ws_id, Membership.app_user_id == app_user_id
        )
    ).first()
    if taken is not None:
        raise AlreadyExistsError("this CRM identity is already linked to another member")


def add_membership(
    db: Session,
    user: UserAccount,
    ws: Workspace,
    *,
    role: str = "rep",
    see_all: bool = False,
    delete_own: bool = False,
    app_user_id: uuid.UUID | None = None,
) -> Membership:
    if get_membership(db, user.id, ws.id) is not None:
        raise AlreadyExistsError("this person is already a member of the workspace")
    if user.is_demo and not ws.is_demo:
        raise InvalidInputError("a demo account can only belong to a test workspace")
    check_app_user(db, ws.id, app_user_id)
    row = Membership(
        user_account_id=user.id,
        workspace_id=ws.id,
        role=role,
        see_all=see_all,
        delete_own=delete_own,
        app_user_id=app_user_id,
    )
    db.add(row)
    db.flush()
    return row


def get_membership(db: Session, user_id: uuid.UUID, ws_id: uuid.UUID) -> Membership | None:
    return db.scalars(
        select(Membership).where(
            Membership.user_account_id == user_id, Membership.workspace_id == ws_id
        )
    ).one_or_none()


def give_admin_everywhere(db: Session, user: UserAccount) -> None:
    """An admin membership in every workspace the user does not belong to yet."""
    for ws in db.scalars(select(Workspace)):
        if get_membership(db, user.id, ws.id) is None:
            add_membership(db, user, ws, role="admin")


def list_members(db: Session, ws_id: uuid.UUID) -> list[tuple[Membership, UserAccount, str | None]]:
    rows = db.execute(
        select(Membership, UserAccount, AppUser.display_name)
        .join(UserAccount, UserAccount.id == Membership.user_account_id)
        .outerjoin(AppUser, AppUser.id == Membership.app_user_id)
        .where(Membership.workspace_id == ws_id)
        .order_by(UserAccount.display_name, UserAccount.email)
    )
    return [(m, u, n) for m, u, n in rows.all()]


def demo_logins(db: Session, limit: int = 12) -> list[tuple[str, str]]:
    """(email, name) of enabled non-admin accounts with an empty password whose memberships are
    all in demo workspaces. The caller checks that the app runs on loopback."""
    rows = db.execute(
        select(UserAccount.email, UserAccount.display_name)
        .where(
            UserAccount.is_admin.is_(False),
            UserAccount.disabled.is_(False),
            UserAccount.password_hash.is_(None),
            UserAccount.is_demo.is_(False),  # those use the "Try the demo" button
            select(Membership.id).where(Membership.user_account_id == UserAccount.id).exists(),
            ~select(Membership.id)
            .join(Workspace, Workspace.id == Membership.workspace_id)
            .where(Membership.user_account_id == UserAccount.id, Workspace.is_demo.is_(False))
            .exists(),
        )
        .order_by(UserAccount.email)
        .limit(limit)
    ).all()
    return [(e, n) for e, n in rows]
