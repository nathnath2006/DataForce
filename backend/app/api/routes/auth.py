"""Sign-in: status, first-run setup, login, logout, me."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.api.deps import AppSettings, Db, SessionUser
from app.api.schemas_auth import (
    AuthStatus,
    AuthUserOut,
    DemoLogin,
    ForgotIn,
    JoinIn,
    LoginIn,
    MembershipOut,
    MeOut,
    ResetIn,
    SetupIn,
    SignupIn,
)
from app.auth import passwords, ratelimit, reset, sessions
from app.auth.access import empty_password_allowed, is_loopback
from app.config import Settings, is_hosted, ui_origin
from app.db.models import AppUser, Membership, UserAccount, Workspace
from app.services import access_codes, mailer, user_accounts
from app.services.errors import AlreadyExistsError

log = logging.getLogger(__name__)
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
        secure=is_hosted(settings) or not is_loopback(settings),
    )


def _user_out(u: UserAccount) -> AuthUserOut:
    return AuthUserOut(
        id=u.id,
        email=u.email,
        display_name=u.display_name,
        is_admin=u.is_admin,
        workspace_credits=u.workspace_credits,
    )


@router.get("/status", response_model=AuthStatus)
def status(
    request: Request,
    db: Db,
    settings: AppSettings,
    df_session: Annotated[str | None, Cookie()] = None,
) -> AuthStatus:
    demo = user_accounts.demo_logins(db) if is_loopback(settings) else []
    return AuthStatus(
        setup_needed=not user_accounts.admin_exists(db),
        signed_in=getattr(request.state, "user_id", None) is not None,
        signup_enabled=settings.signup_enabled,
        demo_logins=[DemoLogin(email=e, display_name=n) for e, n in demo],
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


@router.post("/forgot", status_code=202)
def forgot(body: ForgotIn, request: Request, db: Db, settings: AppSettings) -> dict[str, bool]:
    """Always the same answer. The reset link is emailed; without SMTP it goes to the server log."""
    email = "forgot:" + body.email.strip().lower()
    client = "forgot:" + (request.client.host if request.client else "unknown")
    try:
        ratelimit.check(email, client)
    except ratelimit.TooManyAttempts as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None
    ratelimit.record_failure(email, client)
    user = user_accounts.get_by_email(db, body.email)
    if user is not None and not user.disabled:
        token = reset.make_token(settings, user)
        if token is not None:
            link = f"{ui_origin(settings)}/reset?token={token}"
            if mailer.is_configured(settings):
                mailer.send_async(
                    settings,
                    user.email,
                    "Reset your DataForce password",
                    "Someone asked to reset the password of your DataForce account.\n\n"
                    f"Open this link within 15 minutes to choose a new password:\n{link}\n\n"
                    "If this was not you, ignore this email: your password stays as it is.\n",
                )
            elif is_hosted(settings):
                log.warning("Password reset requested but email is not configured")
            else:
                log.warning("Password reset link for %s (valid 15 minutes): %s", user.email, link)
    return {"accepted": True}


@router.post("/reset", response_model=MeOut)
def reset_password(
    body: ResetIn, request: Request, response: Response, db: Db, settings: AppSettings
) -> MeOut:
    client = "reset:" + (request.client.host if request.client else "unknown")
    try:
        ratelimit.check(client, client)
    except ratelimit.TooManyAttempts as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None
    bad = HTTPException(status_code=400, detail="This link is invalid or expired.")
    parsed = reset.parse_token(body.token)
    user = db.get(UserAccount, parsed[0]) if parsed else None
    if parsed is None or user is None or not reset.verify(settings, user, parsed[1], parsed[2]):
        ratelimit.record_failure(client, client)
        raise bad
    user.password_hash = passwords.hash_for_new_password(
        body.password, empty_allowed=empty_password_allowed(db, settings, user)
    )
    sessions.end_all_sessions(db, user.id)
    token = sessions.create_session(db, user, request.headers.get("user-agent"))
    db.commit()
    set_cookie(response, token, settings)
    return _me(db, user)


_BAD_CODE = access_codes.GENERIC_ERROR


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/signup", response_model=MeOut, status_code=201)
def signup(
    body: SignupIn, request: Request, response: Response, db: Db, settings: AppSettings
) -> MeOut:
    """Public sign-up with a creation code (mode create) or a join token (mode join). Every
    failure about the code or the email gives the same answer."""
    if not settings.signup_enabled:
        raise HTTPException(status_code=403, detail="sign-up is closed")
    email = body.email.strip().lower()
    client = "signup:" + _client(request)
    key = "signup:" + email
    try:
        ratelimit.check(key, client)
    except ratelimit.TooManyAttempts as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None
    # Hash first: a bad code costs the same time as a good one.
    pw_hash = passwords.hash_for_new_password(body.password, empty_allowed=False)

    def fail() -> HTTPException:
        db.rollback()
        ratelimit.record_failure(key, client)
        return HTTPException(status_code=400, detail=_BAD_CODE)

    if user_accounts.get_by_email(db, email) is not None:
        raise fail()
    row = (
        access_codes.consume_code(db, body.code)
        if body.mode == "create"
        else access_codes.consume_join_token(db, body.code)
    )
    if row is None:
        raise fail()
    try:
        user = user_accounts.create_account(db, email, body.display_name, pw_hash)
        if body.mode == "create":
            user.workspace_credits = 1
        else:
            ws = db.get(Workspace, row.workspace_id)
            if ws is None:
                raise fail()
            user_accounts.add_membership(db, user, ws, role=row.role)
        token = sessions.create_session(db, user, request.headers.get("user-agent"))
        db.commit()
    except (AlreadyExistsError, IntegrityError):
        raise fail() from None
    set_cookie(response, token, settings)
    return _me(db, user)


@router.post("/join", response_model=MeOut)
def join(body: JoinIn, request: Request, db: Db, user: SessionUser) -> MeOut:
    """A signed-in person joins a workspace with a join token."""
    client = "join:" + _client(request)
    key = f"join:{user.id}"
    try:
        ratelimit.check(key, client)
    except ratelimit.TooManyAttempts as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None
    row = access_codes.consume_join_token(db, body.token)
    ws = db.get(Workspace, row.workspace_id) if row is not None else None
    if row is None or ws is None or user_accounts.get_membership(db, user.id, ws.id) is not None:
        db.rollback()
        ratelimit.record_failure(key, client)
        raise HTTPException(status_code=400, detail=_BAD_CODE)
    user_accounts.add_membership(db, user, ws, role=row.role)
    db.commit()
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
