"""Workspaces: one team's data, or one synthetic demo dataset."""

from __future__ import annotations

import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Workspace
from app.services._common import erasure
from app.services.errors import AlreadyExistsError, InvalidInputError, NotFoundError
from app.services.textclean import scrub_text

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def create_workspace(session: Session, slug: str, name: str, *, is_demo: bool = False) -> Workspace:
    slug = scrub_text(slug).strip()
    name = scrub_text(name).strip()
    if not _SLUG.match(slug):
        raise InvalidInputError("workspace slug must be 1-64 chars of a-z, 0-9 and '-'")
    if not name:
        raise InvalidInputError("workspace name is empty")
    if get_workspace_by_slug(session, slug) is not None:
        raise AlreadyExistsError(f"workspace {slug!r} already exists")
    ws = Workspace(slug=slug, name=name, is_demo=is_demo)
    session.add(ws)
    session.flush()
    return ws


def get_workspace_by_slug(session: Session, slug: str) -> Workspace | None:
    return session.scalars(select(Workspace).where(Workspace.slug == slug)).one_or_none()


def list_workspaces(session: Session) -> list[Workspace]:
    return list(session.scalars(select(Workspace).order_by(Workspace.slug)))


def delete_workspace(session: Session, slug: str) -> None:
    """Hard-delete a workspace and everything in it (notes included, hence the erasure flag)."""
    ws = get_workspace_by_slug(session, slug)
    if ws is None:
        raise NotFoundError(f"workspace {slug!r} not found")
    with erasure(session):
        session.execute(
            delete(Workspace)
            .where(Workspace.id == ws.id)
            .execution_options(synchronize_session=False)
        )
