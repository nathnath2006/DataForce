"""Accounts (companies)."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Account, Contact, Deal
from app.domain.enums import CLOSED_STAGES
from app.domain.schemas import AccountIn
from app.services._common import (
    LIKE_ESCAPE,
    erasure,
    get_scoped,
    like_contains,
    pairs,
    require_account,
    require_workspace,
)
from app.services.errors import InvalidInputError
from app.services.textclean import scrub_optional, scrub_text


def create_account(session: Session, ws_id: uuid.UUID, data: AccountIn) -> Account:
    require_workspace(session, ws_id)
    account = Account(
        workspace_id=ws_id,
        name=scrub_text(data.name),
        domain=scrub_optional(data.domain),
        industry=scrub_optional(data.industry),
        segment=data.segment.value if data.segment else None,
        employee_count=data.employee_count,
        region=scrub_optional(data.region),
        country=scrub_optional(data.country.upper()) if data.country else None,
        source=data.source.value,
        external_ref=scrub_optional(data.external_ref),
    )
    session.add(account)
    session.flush()
    return account


def get_account(session: Session, ws_id: uuid.UUID, account_id: uuid.UUID) -> Account | None:
    return get_scoped(session, Account, ws_id, account_id)


def list_accounts(session: Session, ws_id: uuid.UUID) -> list[Account]:
    stmt = select(Account).where(Account.workspace_id == ws_id).order_by(Account.name, Account.id)
    return list(session.scalars(stmt))


def erase_account(session: Session, ws_id: uuid.UUID, account_id: uuid.UUID) -> None:
    """GDPR erasure: the account, its contacts, deals, comments and the contacts' notes are
    hard-deleted by the FK cascade."""
    require_account(session, ws_id, account_id)
    with erasure(session):
        session.execute(
            delete(Account)
            .where(Account.id == account_id, Account.workspace_id == ws_id)
            .execution_options(synchronize_session=False)
        )


_UPDATABLE = ("name", "domain", "industry", "segment", "employee_count", "region", "country")


def update_account(
    session: Session, ws_id: uuid.UUID, account_id: uuid.UUID, changes: dict[str, Any]
) -> Account:
    """Partial update: only the keys of `changes` are touched, an explicit None clears a field
    (except `name`, which cannot be cleared)."""
    account = require_account(session, ws_id, account_id)
    unknown = set(changes) - set(_UPDATABLE)
    if unknown:
        raise InvalidInputError(f"cannot update: {', '.join(sorted(unknown))}")
    for key, value in changes.items():
        if isinstance(value, Enum):
            value = value.value
        if key == "name":
            value = scrub_text(value).strip() if value is not None else None
            if not value:
                raise InvalidInputError("name cannot be empty")
        elif key == "country":
            value = scrub_optional(value.upper()) if value else None
        elif isinstance(value, str):
            value = scrub_optional(value)
        setattr(account, key, value)
    session.flush()
    return account


def list_accounts_page(
    session: Session,
    ws_id: uuid.UUID,
    *,
    q: str | None = None,
    segment: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[Account], int]:
    """A page of accounts (by name) and the total matching. `q` is a literal, case-insensitive
    substring of the name or the domain."""
    cond = [Account.workspace_id == ws_id]
    if q:
        pattern = like_contains(q)
        cond.append(
            or_(
                Account.name.ilike(pattern, escape=LIKE_ESCAPE),
                Account.domain.ilike(pattern, escape=LIKE_ESCAPE),
            )
        )
    if segment:
        cond.append(Account.segment == segment)
    total = session.scalar(select(func.count()).select_from(Account).where(*cond)) or 0
    stmt = select(Account).where(*cond).order_by(Account.name, Account.id)
    return list(session.scalars(stmt.limit(limit).offset(offset))), total


def account_counts(
    session: Session, ws_id: uuid.UUID, account_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int, int]]:
    """{account id: (n_contacts, n_deals, n_open_deals)} from two grouped queries."""
    if not account_ids:
        return {}
    contacts = pairs(
        session.execute(
            select(Contact.account_id, func.count(Contact.id))
            .where(Contact.workspace_id == ws_id, Contact.account_id.in_(account_ids))
            .group_by(Contact.account_id)
        )
    )
    closed = [s.value for s in CLOSED_STAGES]
    deals = {
        aid: (n, o)
        for aid, n, o in session.execute(
            select(
                Deal.account_id,
                func.count(Deal.id),
                func.coalesce(func.sum(case((Deal.stage.in_(closed), 0), else_=1)), 0),
            )
            .where(Deal.workspace_id == ws_id, Deal.account_id.in_(account_ids))
            .group_by(Deal.account_id)
        )
    }
    return {
        aid: (contacts.get(aid, 0), *(int(x) for x in deals.get(aid, (0, 0))))  # type: ignore[misc]
        for aid in account_ids
    }
