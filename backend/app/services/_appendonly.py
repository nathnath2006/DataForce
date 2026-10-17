"""Shared logic of notes (on a contact) and comments (on an account): append-only chains.

A chain is an original row plus its corrections (each points at the row it corrects through
`corrects_id`). The DB trigger enforces immutability; this module builds on it: a correction is
an INSERT, a delete is a one-time UPDATE of deleted_at / deleted_by_id."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services._common import require_user
from app.services.errors import InvalidInputError, NotFoundError
from app.services.textclean import scrub_text

BODY_MAX_CHARS = 20_000


def clean_body(body: str) -> str:
    body = scrub_text(body).strip()
    if not body:
        raise InvalidInputError("the text is empty")
    if len(body) > BODY_MAX_CHARS:
        raise InvalidInputError(f"the text is longer than {BODY_MAX_CHARS} characters")
    return body


def _siblings(
    session: Session,
    model: Any,
    parent_col: str,
    ws_id: uuid.UUID,
    parent_id: Any,
    *,
    lock: bool = False,
):
    """Every row of the parent. `lock=True` takes row locks (SELECT ... FOR UPDATE) and refreshes
    the rows, so a concurrent correction / delete of the same chain waits and then sees it."""
    column = getattr(model, parent_col)
    stmt = select(model).where(model.workspace_id == ws_id, column == parent_id)
    if lock:
        stmt = stmt.order_by(model.id).with_for_update().execution_options(populate_existing=True)
    return list(session.scalars(stmt))


def _chains(rows: list[Any]) -> list[list[Any]]:
    """Group rows into chains, each ordered oldest first (root, then its correction, ...)."""
    child = {r.corrects_id: r for r in rows if r.corrects_id is not None}
    chains = []
    for root in sorted((r for r in rows if r.corrects_id is None), key=lambda r: r.created_at):
        chain, row = [root], child.get(root.id)
        while row is not None and len(chain) <= len(rows):
            chain.append(row)
            row = child.get(row.id)
        chains.append(chain)
    return chains


def _checked_time(at: datetime | None, not_before: datetime | None = None) -> datetime:
    now = datetime.now(UTC)
    if at is None:
        return now
    if at.tzinfo is None:
        raise InvalidInputError("created_at must be timezone-aware")
    if at > now:
        raise InvalidInputError("created_at is in the future")
    if not_before is not None and at < not_before:
        raise InvalidInputError("a correction cannot be older than the version it corrects")
    return at


def add(
    session: Session,
    model: Any,
    parent_col: str,
    ws_id: uuid.UUID,
    parent_id: uuid.UUID,
    author_id: uuid.UUID | None,
    body: str,
    *,
    created_at: datetime | None = None,
) -> Any:
    """`created_at` keeps the original date of imported history (an old CRM's notes, the
    synthetic demo); it is checked, never in the future. Default: now."""
    if author_id is not None:
        require_user(session, ws_id, author_id)
    # created_at from Python: now() is the transaction start, identical for every row of a load.
    row = model(
        workspace_id=ws_id,
        **{parent_col: parent_id},
        author_id=author_id,
        body=clean_body(body),
        created_at=_checked_time(created_at),
    )
    session.add(row)
    session.flush()
    return row


def _require_row(session: Session, model: Any, ws_id: uuid.UUID, row_id: uuid.UUID) -> Any:
    row = session.get(model, row_id)
    if row is None or row.workspace_id != ws_id:
        raise NotFoundError(f"{model.__tablename__} {row_id} not found in this workspace")
    return row


def history(
    session: Session,
    model: Any,
    parent_col: str,
    ws_id: uuid.UUID,
    row_id: uuid.UUID,
    *,
    lock: bool = False,
) -> list[Any]:
    row = _require_row(session, model, ws_id, row_id)
    rows = _siblings(session, model, parent_col, ws_id, getattr(row, parent_col), lock=lock)
    for chain in _chains(rows):
        if any(r.id == row_id for r in chain):
            return chain
    return [row]  # unreachable unless the chain is corrupt


def correct(
    session: Session,
    model: Any,
    parent_col: str,
    ws_id: uuid.UUID,
    row_id: uuid.UUID,
    author_id: uuid.UUID | None,
    new_body: str,
    *,
    created_at: datetime | None = None,
) -> Any:
    """Insert a new version of the chain containing `row_id`. The correction attaches to the
    latest version, so chains stay linear. An explicit `created_at` (imported history) must not
    precede the version it corrects."""
    chain = history(session, model, parent_col, ws_id, row_id, lock=True)
    latest = chain[-1]
    if latest.deleted_at is not None:
        raise InvalidInputError("cannot correct a deleted entry")
    if author_id is not None:
        require_user(session, ws_id, author_id)
    row = model(
        workspace_id=ws_id,
        **{parent_col: getattr(latest, parent_col)},
        author_id=author_id,
        body=clean_body(new_body),
        corrects_id=latest.id,
        created_at=_checked_time(created_at, not_before=latest.created_at),
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        raise InvalidInputError(
            f"{model.__tablename__} was corrected concurrently, retry"
        ) from None
    return row


def soft_delete(
    session: Session,
    model: Any,
    parent_col: str,
    ws_id: uuid.UUID,
    row_id: uuid.UUID,
    by_id: uuid.UUID | None,
) -> Any:
    """Soft-delete the whole chain (every version not already deleted). Returns the latest
    version. Deleting something already deleted is refused."""
    chain = history(session, model, parent_col, ws_id, row_id, lock=True)
    live = [r for r in chain if r.deleted_at is None]
    if not live:
        raise InvalidInputError("already deleted")
    if by_id is not None:
        require_user(session, ws_id, by_id)
    now = datetime.now(UTC)
    for row in live:
        row.deleted_at = now
        row.deleted_by_id = by_id
    session.flush()
    return chain[-1]


def current(
    session: Session, model: Any, parent_col: str, ws_id: uuid.UUID, parent_id: uuid.UUID
) -> list[Any]:
    """Latest version of each chain, not deleted, oldest chain first."""
    rows = _siblings(session, model, parent_col, ws_id, parent_id)
    heads = [chain[-1] for chain in _chains(rows)]
    return [h for h in heads if h.deleted_at is None]
