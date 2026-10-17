"""Helpers shared by the CRM services (scoped lookups and the GDPR-erasure switch)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import Account, AppUser, Contact, Deal, Workspace
from app.services.errors import NotFoundError


def pairs(result) -> dict:
    """{first column: second column} of a two-column result."""
    return dict(result.all())


def like_contains(term: str) -> str:
    """LIKE pattern matching `term` as a literal substring (`%`, `_` and `\\` escaped). Use with
    `column.ilike(pattern, escape="\\")`; the pattern is always a bound parameter."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


LIKE_ESCAPE = "\\"


def get_scoped[T](
    session: Session, model: type[T], ws_id: uuid.UUID, row_id: uuid.UUID
) -> T | None:
    """The row only when it belongs to `ws_id`: a service never touches another workspace."""
    row = session.get(model, row_id)
    if row is None or getattr(row, "workspace_id", None) != ws_id:
        return None
    return row


def require[T](session: Session, model: type[T], ws_id: uuid.UUID, row_id: uuid.UUID) -> T:
    row = get_scoped(session, model, ws_id, row_id)
    if row is None:
        raise NotFoundError(f"{model.__tablename__} {row_id} not found in this workspace")  # type: ignore[attr-defined]
    return row


def require_workspace(session: Session, ws_id: uuid.UUID) -> Workspace:
    ws = session.get(Workspace, ws_id)
    if ws is None:
        raise NotFoundError(f"workspace {ws_id} not found")
    return ws


def require_account(session: Session, ws_id: uuid.UUID, account_id: uuid.UUID) -> Account:
    return require(session, Account, ws_id, account_id)


def require_contact(session: Session, ws_id: uuid.UUID, contact_id: uuid.UUID) -> Contact:
    return require(session, Contact, ws_id, contact_id)


def require_user(session: Session, ws_id: uuid.UUID, user_id: uuid.UUID) -> AppUser:
    return require(session, AppUser, ws_id, user_id)


def require_deal(session: Session, ws_id: uuid.UUID, deal_id: uuid.UUID) -> Deal:
    return require(session, Deal, ws_id, deal_id)


def _set_erasure(session: Session, value: str) -> None:
    # set_config(..., is_local=true) == SET LOCAL, but with a bound parameter.
    session.execute(select(func.set_config("dataforce.erasure", value, True)))


@contextmanager
def erasure(session: Session) -> Iterator[None]:
    """Allow the append-only trigger to let DELETEs through, for this transaction only and only
    around the statement(s) in the block (GDPR erasure, workspace deletion)."""
    _set_erasure(session, "on")
    try:
        yield
    finally:
        try:
            _set_erasure(session, "off")
        except SQLAlchemyError:  # transaction already aborted: the flag dies with it
            pass
        session.expire_all()  # the cascade removed rows the identity map still holds
