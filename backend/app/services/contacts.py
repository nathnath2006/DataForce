"""Contacts (third-party people: strict minimum) and the manual org chart."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.auth import visibility
from app.auth.viewer import Viewer
from app.db.models import Account, Contact, ContactChannel, Note, OrgProposal
from app.domain.schemas import ContactIn
from app.services import activities, documents
from app.services._common import (
    LIKE_ESCAPE,
    erasure,
    get_scoped,
    like_contains,
    order_clauses,
    pairs,
    require_account,
    require_contact,
)
from app.services.errors import InvalidInputError
from app.services.textclean import scrub_optional, scrub_text
from app.services.titles import classify_contact_title


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


def create_contact(
    session: Session, ws_id: uuid.UUID, data: ContactIn, viewer: Viewer | None = None
) -> Contact:
    require_account(session, ws_id, data.account_id, viewer)
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
    classify_contact_title(contact)
    session.add(contact)
    session.flush()
    return contact


def get_contact(session: Session, ws_id: uuid.UUID, contact_id: uuid.UUID) -> Contact | None:
    return get_scoped(session, Contact, ws_id, contact_id)


def set_reports_to(
    session: Session,
    ws_id: uuid.UUID,
    contact_id: uuid.UUID,
    manager_id: uuid.UUID | None,
    viewer: Viewer | None = None,
) -> Contact:
    """Set (or clear, with None) the manager. Refuses cross-account links and cycles."""
    contact = require_contact(session, ws_id, contact_id, viewer)
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
    # A manual change clears the proposal link; accepting a proposal sets it again afterwards.
    contact.reports_to_proposal_id = None
    session.flush()
    return contact


def list_contacts(
    session: Session,
    ws_id: uuid.UUID,
    account_id: uuid.UUID | None = None,
    viewer: Viewer | None = None,
) -> list[Contact]:
    stmt = select(Contact).where(
        Contact.workspace_id == ws_id,
        *visibility.conds(visibility.in_accounts(viewer, Contact.account_id)),
    )
    if account_id is not None:
        stmt = stmt.where(Contact.account_id == account_id)
    return list(session.scalars(stmt.order_by(Contact.full_name, Contact.id)))


def org_chart(
    session: Session, ws_id: uuid.UUID, account_id: uuid.UUID, viewer: Viewer | None = None
) -> list[tuple[Contact, uuid.UUID | None]]:
    """(contact, manager id or None) for every contact of the account."""
    require_account(session, ws_id, account_id, viewer)
    return [(c, c.reports_to_id) for c in list_contacts(session, ws_id, account_id)]


def erase_contact(
    session: Session, ws_id: uuid.UUID, contact_id: uuid.UUID, viewer: Viewer | None = None
) -> None:
    """The "1-click delete": the contact and, by cascade, their notes. People who reported to
    them lose their manager link (FK SET NULL). Never blocked: the proposals that involve them
    are deleted first and the `reports_to_proposal_id` pointers cleared (SR12-01: the FK SET NULL
    re-checked a pointer to a proposal the same cascade had just removed). Their turns and name
    are redacted from the transcripts in the same transaction (SR12-03)."""
    contact = require_contact(session, ws_id, contact_id, viewer)
    with erasure(session):
        involved = (
            select(OrgProposal.id)
            .where(
                OrgProposal.workspace_id == ws_id,
                or_(OrgProposal.contact_id == contact_id, OrgProposal.manager_id == contact_id),
            )
            .scalar_subquery()
        )
        session.execute(
            update(Contact)
            .where(Contact.workspace_id == ws_id, Contact.reports_to_proposal_id.in_(involved))
            .values(reports_to_proposal_id=None)
            .execution_options(synchronize_session=False)
        )
        # Ambiguous proposals that list them as a candidate would keep a dangling id.
        session.execute(
            delete(OrgProposal)
            .where(
                OrgProposal.workspace_id == ws_id,
                or_(
                    OrgProposal.contact_id == contact_id,
                    OrgProposal.manager_id == contact_id,
                    OrgProposal.candidates.contains([str(contact_id)]),
                ),
            )
            .execution_options(synchronize_session=False)
        )
        session.flush()
        documents.redact_contact(session, ws_id, contact)
        activities.redact_contact(session, ws_id, contact)
        session.execute(
            delete(Contact)
            .where(Contact.id == contact_id, Contact.workspace_id == ws_id)
            .execution_options(synchronize_session=False)
        )


def update_contact(
    session: Session,
    ws_id: uuid.UUID,
    contact_id: uuid.UUID,
    changes: dict[str, Any],
    viewer: Viewer | None = None,
) -> Contact:
    """Partial update of the name and the title (the manager has its own function)."""
    contact = require_contact(session, ws_id, contact_id, viewer)
    unknown = set(changes) - {"full_name", "title"}
    if unknown:
        raise InvalidInputError(f"cannot update: {', '.join(sorted(unknown))}")
    if "full_name" in changes:
        name = scrub_text(changes["full_name"]).strip() if changes["full_name"] else ""
        if not name:
            raise InvalidInputError("full_name cannot be empty")
        contact.full_name = name
    if "title" in changes:
        contact.title = scrub_optional(changes["title"])
        classify_contact_title(contact)
    session.flush()
    return contact


CONTACT_SORT = {
    "full_name": Contact.full_name,
    "title": Contact.title,
    "title_function": Contact.title_function,
    "title_seniority": Contact.title_seniority,
}


def list_contacts_page(
    session: Session,
    ws_id: uuid.UUID,
    *,
    account_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = 200,
    offset: int = 0,
    sort: str | None = None,
    direction: str | None = None,
    viewer: Viewer | None = None,
) -> tuple[list[Contact], int]:
    cond = [
        Contact.workspace_id == ws_id,
        *visibility.conds(visibility.in_accounts(viewer, Contact.account_id)),
    ]
    if account_id is not None:
        cond.append(Contact.account_id == account_id)
    if q:
        pattern = like_contains(q)
        cond.append(
            or_(
                Contact.full_name.ilike(pattern, escape=LIKE_ESCAPE),
                Contact.title.ilike(pattern, escape=LIKE_ESCAPE),
            )
        )
    total = session.scalar(select(func.count()).select_from(Contact).where(*cond)) or 0
    order = order_clauses(CONTACT_SORT, sort, direction, [Contact.full_name], Contact.id)
    stmt = select(Contact).where(*cond).order_by(*order)
    return list(session.scalars(stmt.limit(limit).offset(offset))), total


def contact_extras(
    session: Session, ws_id: uuid.UUID, contact_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Per contact: account_name, reports_to_name, n_direct_reports, n_notes (current, not
    deleted: a deleted chain has its root deleted too), n_channels. Grouped queries, no N+1."""
    if not contact_ids:
        return {}
    boss = aliased(Contact)
    names = {
        cid: (acc, bname)
        for cid, acc, bname in session.execute(
            select(Contact.id, Account.name, boss.full_name)
            .join(Account, Account.id == Contact.account_id)
            .outerjoin(boss, boss.id == Contact.reports_to_id)
            .where(Contact.workspace_id == ws_id, Contact.id.in_(contact_ids))
        )
    }
    reports = pairs(
        session.execute(
            select(Contact.reports_to_id, func.count(Contact.id))
            .where(Contact.workspace_id == ws_id, Contact.reports_to_id.in_(contact_ids))
            .group_by(Contact.reports_to_id)
        )
    )
    n_notes = pairs(
        session.execute(
            select(Note.contact_id, func.count(Note.id))
            .where(
                Note.workspace_id == ws_id,
                Note.contact_id.in_(contact_ids),
                Note.corrects_id.is_(None),
                Note.deleted_at.is_(None),
            )
            .group_by(Note.contact_id)
        )
    )
    n_channels = pairs(
        session.execute(
            select(ContactChannel.contact_id, func.count(ContactChannel.id))
            .where(ContactChannel.workspace_id == ws_id, ContactChannel.contact_id.in_(contact_ids))
            .group_by(ContactChannel.contact_id)
        )
    )
    return {
        cid: {
            "account_name": names[cid][0],
            "reports_to_name": names[cid][1],
            "n_direct_reports": reports.get(cid, 0),
            "n_notes": n_notes.get(cid, 0),
            "n_channels": n_channels.get(cid, 0),
        }
        for cid in contact_ids
        if cid in names
    }
