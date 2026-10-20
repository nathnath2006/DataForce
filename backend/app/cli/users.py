"""`dataforce users ...` and the demo login backfill (`dataforce demo backfill-logins`)."""

from __future__ import annotations

from typing import Annotated

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import passwords
from app.auth.access import empty_password_allowed
from app.cli._common import cli_command, console, fail, session_factory
from app.config import get_settings
from app.db.models import UserAccount, Workspace
from app.services import user_accounts, workspaces
from app.services.demo_logins import backfill_logins
from app.services.errors import InvalidInputError, NotFoundError

app = typer.Typer(
    help="Sign-in accounts (list, create, reset a password, disable).",
    no_args_is_help=True,
    add_completion=False,
)

EmailArg = Annotated[str, typer.Argument(help="The account's email.")]
PasswordOpt = Annotated[
    str, typer.Option("--password", help="Empty only for demo workspaces on this computer.")
]


def _workspace(s: Session, slug: str) -> Workspace:
    ws = workspaces.get_workspace_by_slug(s, slug)
    if ws is None:
        raise NotFoundError(f"workspace {slug!r} not found")
    return ws


@app.command("list")
@cli_command
def list_cmd() -> None:
    """List accounts and their workspaces."""
    with session_factory()() as s:
        for u in s.scalars(select(UserAccount).order_by(UserAccount.email)):
            flags = ("admin " if u.is_admin else "") + ("disabled" if u.disabled else "")
            console.print(f"{u.email}  {u.display_name}  {flags}".rstrip(), markup=False)


@app.command("create")
@cli_command
def create_cmd(
    email: EmailArg,
    name: Annotated[str, typer.Option("--name", help="Display name.")],
    password: PasswordOpt = "",
    admin: Annotated[bool, typer.Option("--admin", help="Superadmin (every workspace).")] = False,
    workspace: Annotated[str | None, typer.Option("--workspace", help="Workspace slug.")] = None,
    role: Annotated[str, typer.Option("--role", help="admin or rep.")] = "rep",
) -> None:
    """Create an account, optionally joined to a workspace."""
    if role not in ("admin", "rep"):
        raise fail("--role must be admin or rep")
    with session_factory()() as s:
        ws = _workspace(s, workspace) if workspace else None
        if admin or ws is None:
            allowed = False
        else:
            allowed = empty_password_allowed(s, get_settings(), None, extra_workspace_id=ws.id)
        try:
            pw = passwords.hash_for_new_password(password, empty_allowed=allowed)
        except InvalidInputError as exc:
            raise fail(str(exc)) from None
        user = user_accounts.create_account(s, email, name, pw, is_admin=admin)
        if admin:
            user_accounts.give_admin_everywhere(s, user)
        elif ws is not None:
            user_accounts.add_membership(s, user, ws, role=role)
        s.commit()
    console.print(f"created {email.strip().lower()}", markup=False)


@app.command("reset-password")
@cli_command
def reset_cmd(email: EmailArg, password: PasswordOpt = "") -> None:
    """Set a new password (all the account's sessions end)."""
    with session_factory()() as s:
        user = user_accounts.get_by_email(s, email)
        if user is None:
            raise fail("no such account")
        allowed = empty_password_allowed(s, get_settings(), user)
        try:
            user.password_hash = passwords.hash_for_new_password(password, empty_allowed=allowed)
        except InvalidInputError as exc:
            raise fail(str(exc)) from None
        from app.auth import sessions

        sessions.end_all_sessions(s, user.id)
        s.commit()
    console.print("password updated", markup=False)


@app.command("disable")
@cli_command
def disable_cmd(email: EmailArg) -> None:
    """Disable an account and end its sessions."""
    from app.auth import sessions

    with session_factory()() as s:
        user = user_accounts.get_by_email(s, email)
        if user is None:
            raise fail("no such account")
        if user.is_admin:
            raise fail("the administrator account cannot be disabled")
        user.disabled = True
        sessions.end_all_sessions(s, user.id)
        s.commit()
    console.print("disabled", markup=False)


@cli_command
def backfill_logins_cmd(
    workspace: Annotated[str, typer.Option("--workspace", help="Demo workspace slug.")],
) -> None:
    """Create a login (empty password, role rep) for every CRM user of a demo workspace."""
    with session_factory()() as s:
        created, linked = backfill_logins(s, workspace)
        s.commit()
    console.print(f"{created} accounts created, {linked} linked", markup=False)
