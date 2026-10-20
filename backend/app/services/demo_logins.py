"""One demo account per CRM user of a demo workspace: no password, entered through the demo
button (`POST /api/auth/demo`)."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppUser
from app.services import user_accounts, workspaces
from app.services.errors import InvalidInputError, NotFoundError


def _synthetic_email(name: str, slug: str) -> str:
    parts = re.sub(r"[^a-z0-9 ]", "", name.lower()).split()
    return f"{'.'.join(parts) or 'user'}@{slug}.demo"


def backfill_logins(s: Session, slug: str, *, email_slug: str | None = None) -> tuple[int, int]:
    """One rep account per CRM user of a demo workspace, marked as demo accounts. Returns
    (created, linked). `email_slug` names the synthetic addresses (the nightly rebuild works under
    a temporary slug but wants the same addresses every night, so the accounts are kept)."""
    ws = workspaces.get_workspace_by_slug(s, slug)
    if ws is None:
        raise NotFoundError(f"workspace {slug!r} not found")
    if not ws.is_demo:
        raise InvalidInputError("backfill-logins only works on demo workspaces")
    created = linked = 0
    for au in s.scalars(select(AppUser).where(AppUser.workspace_id == ws.id)):
        if any(m.app_user_id == au.id for m, _, _ in user_accounts.list_members(s, ws.id)):
            continue
        email = (au.email or "").strip().lower() or _synthetic_email(
            au.display_name, email_slug or slug
        )
        user = user_accounts.get_by_email(s, email)
        if user is None:
            user = user_accounts.create_account(s, email, au.display_name, None, is_demo=True)
            created += 1
        elif user.is_admin or user_accounts.get_membership(s, user.id, ws.id) is not None:
            continue  # never touch an admin or an existing member
        if user.password_hash is None:
            user.is_demo = True  # never an account that has a real password
        user_accounts.add_membership(s, user, ws, role="rep", app_user_id=au.id)
        linked += 1
    return created, linked
