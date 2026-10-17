"""Contacts (third-party people: strict minimum) and the manual org chart."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import Contact
from app.domain.schemas import ContactIn
from app.services._common import erasure, get_scoped, require_account, require_contact
from app.services.errors import InvalidInputError
from app.services.textclean import scrub_optional, scrub_text


def _check_manager(
    session: Session, ws_id: uuid.UUID, account_id: uuid.UUID, manager_id: uuid.UUID
) -> Contact:
    manager = require_contact(session, ws_id, manager_id)
    if manager.account_id != account_id:
        raise InvalidInputError("a contact can only report to someone of the same account")
    return manager


# Namespace of the per-account advisory lock that serialises edits of one org chart (SR4-05).
_ORG_CHART_LOCK_NS = 7_461_220_002


def _lock_org_chart(session: Session, account_id: uuid.UUID) -> None:
    """Transaction-level advisory lock on the account: two reporting-line edits of one account
    run one after the other, so the cycle check below never reads a stale snapshot."""
    session.execute(
        select(
            func.pg_advisory_xact_lock(func.hashtextextended(str(account_id), _ORG_CHART_LOCK_NS))
        )
    )


def create_contact(session: Session, ws_id: uuid.UUID, data: ContactIn) -> Contact:
    require_account(session, ws_id, data.account_id)
    if data.reports_to_id is not None:
        _lock_org_chart(session, data.account_id)
        _check_manager(session, ws_id, data.account_id, data.reports_to_id)
    contact = Contact(
        workspace_id=ws_id,
        account_id=data.account_id,
        full_name=scrub_text(data.full_name),
        title=scrub_optional(data.title),
        reports_to_id=data.reports_to_id,
        source=data.source.value,
        source_ref=scrub_optional(data.source_ref),
    )
    session.add(contact)
    session.flush()
    return contact


def get_contact(session: Session, ws_id: uuid.UUID, contact_id: uuid.UUID) -> Contact | None:
    return get_scoped(session, Contact, ws_id, contact_id)


def set_reports_to(
    session: Session, ws_id: uuid.UUID, contact_id: uuid.UUID, manager_id: uuid.UUID | None
) -> Contact:
    """Set (or clear, with None) the manager. Refuses cross-account links and cycles."""
    contact = require_contact(session, ws_id, contact_id)
    if manager_id is not None:
        _lock_org_chart(session, contact.account_id)
        if manager_id == contact_id:
            raise InvalidInputError("a contact cannot report to themselves")
        _check_manager(session, ws_id, contact.account_id, manager_id)
        # Walk up from the proposed manager: reaching `contact` would close a loop.
        rows = session.execute(
            select(Contact.id, Contact.reports_to_id).where(
                Contact.workspace_id == ws_id, Contact.account_id == contact.account_id
            )
        )
        parents = {cid: boss for cid, boss in rows}
        current: uuid.UUID | None = manager_id
        seen: set[uuid.UUID] = set()
        while current is not None and current not in seen:
            if current == contact_id:
                raise InvalidInputError("this reporting line would create a cycle")
            seen.add(current)
            current = parents.get(current)
    contact.reports_to_id = manager_id
    session.flush()
    return contact


def list_contacts(
    session: Session, ws_id: uuid.UUID, account_id: uuid.UUID | None = None
) -> list[Contact]:
    stmt = select(Contact).where(Contact.workspace_id == ws_id)
    if account_id is not None:
        stmt = stmt.where(Contact.account_id == account_id)
    return list(session.scalars(stmt.order_by(Contact.full_name, Contact.id)))


def org_chart(
    session: Session, ws_id: uuid.UUID, account_id: uuid.UUID
) -> list[tuple[Contact, uuid.UUID | None]]:
    """(contact, manager id or None) for every contact of the account."""
    require_account(session, ws_id, account_id)
    return [(c, c.reports_to_id) for c in list_contacts(session, ws_id, account_id)]


def erase_contact(session: Session, ws_id: uuid.UUID, contact_id: uuid.UUID) -> None:
    """The "1-click delete": the contact and, by cascade, their notes. People who reported to
    them lose their manager link (FK SET NULL)."""
    require_contact(session, ws_id, contact_id)
    with erasure(session):
        session.execute(
            delete(Contact)
            .where(Contact.id == contact_id, Contact.workspace_id == ws_id)
            .execution_options(synchronize_session=False)
        )
