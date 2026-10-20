"""Where the empty password is allowed (contract rule 4)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, is_hosted, is_loopback_host
from app.db.models import Membership, UserAccount, Workspace


def is_loopback(settings: Settings) -> bool:
    """Never true when hosted: a loopback UI_HOST says nothing about who can reach the app."""
    return not is_hosted(settings) and is_loopback_host(settings.ui_host)


def empty_password_allowed(
    db: Session,
    settings: Settings,
    user: UserAccount | None,
    *,
    extra_workspace_id: uuid.UUID | None = None,
) -> bool:
    """True when the app runs on loopback, the person is not a superadmin, and every workspace
    they belong to (plus `extra_workspace_id`, being joined now) is a demo workspace, with at
    least one such workspace."""
    if not is_loopback(settings) or (user is not None and user.is_admin):
        return False
    flags: list[bool] = []
    if user is not None:
        flags += list(
            db.scalars(
                select(Workspace.is_demo)
                .join(Membership, Membership.workspace_id == Workspace.id)
                .where(Membership.user_account_id == user.id)
            )
        )
    if extra_workspace_id is not None:
        ws = db.get(Workspace, extra_workspace_id)
        flags.append(bool(ws and ws.is_demo))
    return bool(flags) and all(flags)
