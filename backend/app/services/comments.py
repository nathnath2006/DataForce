"""Comments on accounts. Same API and rules as notes (see notes.py)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.auth import visibility
from app.auth.viewer import Viewer
from app.db.models import Comment
from app.services import _appendonly as ao
from app.services._common import require_account

_PARENT = "account_id"


def add_comment(
    session: Session,
    ws_id: uuid.UUID,
    account_id: uuid.UUID,
    author_id: uuid.UUID | None,
    body: str,
    *,
    created_at: datetime | None = None,
    viewer: Viewer | None = None,
) -> Comment:
    require_account(session, ws_id, account_id, viewer)
    return ao.add(
        session, Comment, _PARENT, ws_id, account_id, author_id, body, created_at=created_at
    )


def correct_comment(
    session: Session,
    ws_id: uuid.UUID,
    comment_id: uuid.UUID,
    author_id: uuid.UUID | None,
    new_body: str,
    *,
    created_at: datetime | None = None,
    viewer: Viewer | None = None,
) -> Comment:
    _check(session, ws_id, comment_id, viewer)
    return ao.correct(
        session, Comment, _PARENT, ws_id, comment_id, author_id, new_body, created_at=created_at
    )


def _check(
    session: Session, ws_id: uuid.UUID, comment_id: uuid.UUID, viewer: Viewer | None
) -> Comment:
    """The comment must exist and belong to an account the viewer may see."""
    row = ao.require_row(session, Comment, ws_id, comment_id)
    visibility.check_account(session, viewer, row.account_id)
    return row


def delete_comment(
    session: Session,
    ws_id: uuid.UUID,
    comment_id: uuid.UUID,
    by_id: uuid.UUID | None,
    viewer: Viewer | None = None,
) -> Comment:
    row = _check(session, ws_id, comment_id, viewer)
    if viewer is not None:
        visibility.require_delete(viewer, row.author_id)
    return ao.soft_delete(session, Comment, _PARENT, ws_id, comment_id, by_id)


def current_comments(
    session: Session, ws_id: uuid.UUID, account_id: uuid.UUID, viewer: Viewer | None = None
) -> list[Comment]:
    require_account(session, ws_id, account_id, viewer)
    return ao.current(session, Comment, _PARENT, ws_id, account_id)


def comment_history(
    session: Session, ws_id: uuid.UUID, comment_id: uuid.UUID, viewer: Viewer | None = None
) -> list[Comment]:
    _check(session, ws_id, comment_id, viewer)
    return ao.history(session, Comment, _PARENT, ws_id, comment_id)
