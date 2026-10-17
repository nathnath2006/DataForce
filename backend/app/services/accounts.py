"""Accounts (companies)."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Account
from app.domain.schemas import AccountIn
from app.services._common import erasure, get_scoped, require_account, require_workspace
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
