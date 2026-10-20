"""Sign-in: status, first-run setup, login, logout, me."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from sqlalchemy import select, text

from app.api.deps import AppSettings, Db, SessionUser
from app.api.schemas_auth import AuthStatus, AuthUserOut, LoginIn, MembershipOut, MeOut, SetupIn
from app.auth import passwords, ratelimit, sessions
from app.auth.access import empty_password_allowed, is_loopback
from app.config import Settings
from app.db.models import AppUser, Membership, UserAccount, Workspace
from app.services import user_accounts

router = APIRouter(prefix="/auth", tags=["auth"])

SETUP_LOCK_KEY = 7_204_001  # pg_advisory_xact_lock key for the first-run setup
_BAD_LOGIN = "wrong email or password"


def set_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        sessions.COOKIE,
        token,
        max_age=int(sessions.ABSOLUTE.total_seconds()),
        httponly=True,
        samesite="lax",
        path="/",
        secure=not is_loopback(settings),
    )


def _user_out(u: UserAccount) -> AuthUserOut:
    return AuthUserOut(id=u.id, email=u.email, display_name=u.display_name, is_admin=u.is_admin)


@router.get("/status", response_model=AuthStatus)
def status(
    request: Request, db: Db, df_session: Annotated[str | None, Cookie()] = None
) -> AuthStatus:
    return AuthStatus(
        setup_needed=not user_accounts.admin_exists(db),
        signed_in=getattr(request.state, "user_id", None) is not None,
    )


@router.post("/setup", response_model=MeOut, status_code=201)
def setup(
    body: SetupIn, request: Request, response: Response, db: Db, settings: AppSettings
) -> MeOut:
    # One setup at a time: the lock is held until this transaction ends.
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": SETUP_LOCK_KEY})
    if user_accounts.admin_exists(db):
        raise HTTPException(status_code=403, detail="setup is already done")
    # The superadmin always needs a real password, even on a demo-only install.
    pw_hash = passwords.hash_for_new_password(body.password, empty_allowed=False)
    user = user_accounts.create_account(db, body.email, body.display_name, pw_hash, is_admin=True)
    user_accounts.give_admin_everywhere(db, user)
    token = sessions.create_session(db, user, request.headers.get("user-agent"))
    db.commit()
    set_cookie(response, token, settings)
    return _me(db, user)


@router.post("/login", response_model=MeOut)
def login(
    body: LoginIn, request: Request, response: Response, db: Db, settings: AppSettings
) -> MeOut:
    email = body.email.strip().lower()
    client = request.client.host if request.client else "unknown"
    try:
        ratelimit.check(email, client)
    except ratelimit.TooManyAttempts as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None
    user = user_accounts.get_by_email(db, email)
    ok = False
    if user is None:
        passwords.dummy_verify(body.password)
    elif user.password_hash is None:
        passwords.dummy_verify(body.password)
        ok = body.password == "" and empty_password_allowed(db, settings, user)
    else:
        ok = passwords.verify_password(body.password, user.password_hash)
    if not ok or user is None or user.disabled:
        ratelimit.record_failure(email, client)
        raise HTTPException(status_code=401, detail=_BAD_LOGIN)
    ratelimit.clear_email(email)
    token = sessions.create_session(db, user, request.headers.get("user-agent"))
    db.commit()
    set_cookie(response, token, settings)
    return _me(db, user)


@router.post("/logout", status_code=204)
def logout(response: Response, db: Db, df_session: Annotated[str | None, Cookie()] = None) -> None:
    sessions.end_session(db, df_session)
    db.commit()
    response.delete_cookie(sessions.COOKIE, path="/")


def _me(db: Db, user: UserAccount) -> MeOut:
    rows = db.execute(
        select(Membership, Workspace, AppUser.display_name)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .outerjoin(AppUser, AppUser.id == Membership.app_user_id)
        .where(Membership.user_account_id == user.id)
        .order_by(Workspace.slug)
    ).all()
    return MeOut(
        user=_user_out(user),
        memberships=[
            MembershipOut(
                workspace_slug=w.slug,
                workspace_name=w.name,
                role="admin" if m.role == "admin" else "rep",
                see_all=m.see_all,
                delete_own=m.delete_own,
                app_user_id=m.app_user_id,
                app_user_name=name,
            )
            for m, w, name in rows
        ],
    )


@router.get("/me", response_model=MeOut)
def me(db: Db, user: SessionUser) -> MeOut:
    return _me(db, user)
