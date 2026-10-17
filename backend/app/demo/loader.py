"""Insert a DemoDataset into the database through the CRM services (no commit here)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.demo.models import DemoDataset
from app.domain.enums import RecordSource
from app.domain.schemas import AccountIn, ContactIn, DealIn, UserIn
from app.services import accounts, comments, contacts, deals, notes, users, workspaces
from app.services import companies as company_svc
from app.services.errors import InvalidInputError

try:  # TODO(M): agent M writes app/services/documents.py; transcripts are skipped until it exists
    from app.services import documents as document_svc
except ImportError:  # pragma: no cover
    document_svc = None  # type: ignore[assignment]


def load_dataset(
    session: Session,
    dataset: DemoDataset,
    *,
    workspace_slug: str,
    workspace_name: str | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Create a demo workspace (`is_demo=True`) and fill it. Returns the counts and ids.

    `replace=True` first deletes any workspace with that slug (cascade). The caller commits.
    """
    existing = workspaces.get_workspace_by_slug(session, workspace_slug) if replace else None
    if existing is not None:
        if not existing.is_demo:
            raise InvalidInputError(
                f"workspace {workspace_slug!r} is not a demo workspace: refusing to replace it"
            )
        workspaces.delete_workspace(session, workspace_slug)
    ws = workspaces.create_workspace(
        session,
        workspace_slug,
        workspace_name
        or f"Synthetic demo ({dataset.ground_truth.variant}, seed {dataset.ground_truth.seed})",
        is_demo=True,
    )
    ws_id = ws.id

    user_ids: dict[str, uuid.UUID] = {}
    for u in dataset.users:
        data = UserIn(display_name=u.display_name, email=u.email, role=u.role)
        user_ids[u.key] = users.create_user(session, ws_id, data).id

    company_ids: dict[str, uuid.UUID] = {}
    for co in dataset.companies:
        company_ids[co.key] = company_svc.create_company(
            session,
            ws_id,
            name=co.name,
            address_line=co.address_line,
            postal_code=co.postal_code,
            city=co.city,
            country=co.country,
            source=co.source.value,
        ).id

    account_ids: dict[str, uuid.UUID] = {}
    for a in dataset.accounts:
        data = AccountIn(**a.model_dump(exclude={"key"}) | {"source": RecordSource.DEMO})
        account = accounts.create_account(session, ws_id, data)
        if a.key in dataset.account_company:
            account.company_id = company_ids[dataset.account_company[a.key]]
        account_ids[a.key] = account.id

    # Pass 1: contacts without manager; pass 2: reporting lines (the service checks the tree).
    contact_ids: dict[str, uuid.UUID] = {}
    for c in dataset.contacts:
        data = ContactIn(
            account_id=account_ids[c.account_key],
            full_name=c.full_name,
            title=c.title,
            source=RecordSource.DEMO,
            source_ref="synthetic demo dataset",
        )
        contact_ids[c.key] = contacts.create_contact(session, ws_id, data).id
    for c in dataset.contacts:
        if c.reports_to_key is not None:
            contacts.set_reports_to(
                session, ws_id, contact_ids[c.key], contact_ids[c.reports_to_key]
            )

    deal_ids: dict[str, uuid.UUID] = {}
    for d in dataset.deals:
        data = DealIn(
            account_id=account_ids[d.account_key],
            owner_id=user_ids[d.owner_key] if d.owner_key else None,
            name=d.name,
            amount_eur=d.amount_eur,
            stage=d.stage,
            lead_source=d.lead_source,
            created_on=d.created_on,
            closed_on=d.closed_on,
            lost_reason=d.lost_reason,
            source=RecordSource.DEMO,
        )
        deal_ids[d.key] = deals.create_deal(session, ws_id, data).id

    note_ids: dict[str, uuid.UUID] = {}
    n_corrections = 0
    for n in dataset.notes:
        author = user_ids[n.author_key] if n.author_key else None
        if n.corrects_key is None:
            note_ids[n.key] = notes.add_note(
                session, ws_id, contact_ids[n.contact_key], author, n.body, created_at=n.created_at
            ).id
        else:
            note_ids[n.key] = notes.correct_note(
                session, ws_id, note_ids[n.corrects_key], author, n.body, created_at=n.created_at
            ).id
            n_corrections += 1

    comment_ids: dict[str, uuid.UUID] = {}
    c_corrections = 0
    for c in dataset.comments:
        author = user_ids[c.author_key] if c.author_key else None
        if c.corrects_key is None:
            comment_ids[c.key] = comments.add_comment(
                session, ws_id, account_ids[c.account_key], author, c.body, created_at=c.created_at
            ).id
        else:
            comment_ids[c.key] = comments.correct_comment(
                session, ws_id, comment_ids[c.corrects_key], author, c.body, created_at=c.created_at
            ).id
            c_corrections += 1

    n_documents = 0
    if document_svc is not None:
        for doc in dataset.documents:
            document_svc.add_document(
                session,
                ws_id,
                account_id=account_ids[doc.account_key],
                title=doc.title,
                text=doc.text,
                meeting_date=doc.meeting_date,
                deal_id=deal_ids[doc.deal_key],
                source="demo",
            )
            n_documents += 1

    return {
        "workspace_id": ws_id,
        "workspace_slug": workspace_slug,
        "users": len(dataset.users),
        "companies": len(dataset.companies),
        "accounts": len(dataset.accounts),
        "contacts": len(dataset.contacts),
        "deals": len(dataset.deals),
        "notes": len(dataset.notes),
        "note_corrections": n_corrections,
        "comments": len(dataset.comments),
        "comment_corrections": c_corrections,
        "documents": n_documents,
    }
