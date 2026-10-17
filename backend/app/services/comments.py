"""Comments on accounts. Same API and rules as notes (see notes.py)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

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
) -> Comment:
    require_account(session, ws_id, account_id)
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
) -> Comment:
    return ao.correct(
        session, Comment, _PARENT, ws_id, comment_id, author_id, new_body, created_at=created_at
    )


def delete_comment(
    session: Session, ws_id: uuid.UUID, comment_id: uuid.UUID, by_id: uuid.UUID | None
) -> Comment:
    return ao.soft_delete(session, Comment, _PARENT, ws_id, comment_id, by_id)


def current_comments(session: Session, ws_id: uuid.UUID, account_id: uuid.UUID) -> list[Comment]:
    return ao.current(session, Comment, _PARENT, ws_id, account_id)


def comment_history(session: Session, ws_id: uuid.UUID, comment_id: uuid.UUID) -> list[Comment]:
    return ao.history(session, Comment, _PARENT, ws_id, comment_id)
