"""The nightly rebuild of the public demo workspace (`dataforce demo reset`).

The new copy is built under a temporary slug while the app keeps serving the old one. Only the
swap runs in one short transaction: delete the old workspace, rename the new one, end every demo
session (and so every visitor's AI key). The demo admin and the rep accounts keep their rows, so
nothing else needs relinking: their memberships were made on the new copy before the swap.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import delete, text
from sqlalchemy.orm import Session, sessionmaker

from app.auth import demo
from app.db.models import UserSession
from app.demo.activities import backfill_workspace
from app.demo.generator import generate
from app.demo.loader import load_dataset
from app.services import demo_logins, workspaces
from app.services.errors import InvalidInputError

SEED = 42
LOCK_KEY = 7_204_117_042  # Postgres advisory lock: two resets must never overlap
DEFAULT_NAME = "Test data (synthetic)"


def temp_slug(slug: str) -> str:
    return f"{slug[:50]}-rebuild"


def reset_demo(
    factory: sessionmaker[Session], slug: str, say: Callable[[str], None] = lambda _m: None
) -> bool:
    """Rebuild workspace `slug` from the planted seed-42 data. Refuses a workspace that is not a
    test workspace (it would delete real data). Returns False, doing nothing, when another reset
    holds the lock (a session-level advisory lock on a connection kept for the whole rebuild)."""
    with factory() as lock_session:
        lock_session.connection()  # pins one connection: the lock belongs to it
        if not lock_session.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}
        ).scalar_one():
            return False
        try:
            _rebuild(factory, slug, say)
        finally:
            lock_session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            lock_session.commit()
    return True


def _rebuild(factory: sessionmaker[Session], slug: str, say: Callable[[str], None]) -> None:
    with factory() as s:
        target = workspaces.get_workspace_by_slug(s, slug)
        if target is not None and not target.is_demo:
            raise InvalidInputError(f"workspace {slug!r} is not a test workspace: refusing")
    tmp = temp_slug(slug)
    try:
        with factory() as s:
            load_dataset(s, generate("planted", SEED), workspace_slug=tmp, replace=True)
            s.commit()
            say("loaded")
            backfill_workspace(s, tmp)
            s.commit()
            say("activities added")
            demo_logins.backfill_logins(s, tmp, email_slug=slug)
            ws = workspaces.get_workspace_by_slug(s, tmp)
            assert ws is not None
            demo.ensure_accounts(s, ws)
            s.commit()
            say("logins added")
        with factory() as s:  # the swap: one transaction
            old = workspaces.get_workspace_by_slug(s, slug)
            name = DEFAULT_NAME
            if old is not None:
                if not old.is_demo:
                    raise InvalidInputError(f"workspace {slug!r} is not a test workspace: refusing")
                name = old.name
                workspaces.delete_workspace(s, slug)
            new = workspaces.get_workspace_by_slug(s, tmp)
            assert new is not None
            if not new.is_demo:
                raise InvalidInputError("the rebuilt workspace is not a test workspace: refusing")
            new.slug, new.name = slug, name
            s.execute(delete(UserSession).where(UserSession.is_demo.is_(True)))
            s.commit()
            say("swapped")
    except BaseException:
        with factory() as s:  # leave no half-built copy behind
            if workspaces.get_workspace_by_slug(s, tmp) is not None:
                workspaces.delete_workspace(s, tmp)
                s.commit()
        raise
