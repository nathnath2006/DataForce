"""Org-chart proposals (rules + meetings): generation, listing, accept and reject (contract §4)."""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Account, Contact, Document, DocumentChunk, OrgProposal
from app.domain.enums import ProposalKind, ProposalOrigin, ProposalStatus, RunKind, RunStatus
from app.orgchart import meetings as meeting_patterns
from app.orgchart import rules
from app.services import contacts as contact_service
from app.services import runs
from app.services._common import require, require_account, require_user
from app.services.errors import InvalidInputError

CONTRADICTS = "contradicts_current_link"
_OPEN = (ProposalStatus.PROPOSED.value, ProposalStatus.AMBIGUOUS.value)


def _people(contacts: Sequence[Contact]) -> list[rules.Person]:
    return [
        rules.Person(
            c.id, c.account_id, c.title, c.title_function, c.title_seniority, c.reports_to_id
        )
        for c in contacts
    ]


def _blocked(session: Session, ws_id: uuid.UUID, account_id: uuid.UUID) -> set[tuple]:
    """(contact, kind, manager) never to re-propose: every rejected proposal, plus accepted
    signals (already recorded)."""
    blocked: set[tuple] = set()
    rows = session.execute(
        select(OrgProposal.contact_id, OrgProposal.kind, OrgProposal.manager_id, OrgProposal.status)
        .where(OrgProposal.workspace_id == ws_id, OrgProposal.account_id == account_id)
        .where(
            OrgProposal.status.in_([ProposalStatus.REJECTED.value, ProposalStatus.ACCEPTED.value])
        )
    )
    for cid, kind, mid, status in rows:
        if kind == ProposalKind.REPORTS_TO.value:
            if status == ProposalStatus.REJECTED.value:
                blocked.add((cid, kind, mid))
        else:
            blocked.add((cid, kind, None))
    return blocked


def _rule_rows(
    session: Session, ws_id: uuid.UUID, account_id: uuid.UUID, contacts: Sequence[Contact], blocked
) -> list[dict[str, Any]]:
    rejected = [(c, m) for c, k, m in blocked if k == ProposalKind.REPORTS_TO.value and m]
    found = rules.propose_for_account(_people(contacts), rejected)
    return [
        {
            "kind": ProposalKind.REPORTS_TO.value,
            "contact_id": f.contact_id,
            "manager_id": f.manager_id,
            "rule": f.rule,
            "evidence": dict(f.evidence),
            "candidates": [str(c) for c in f.candidates] or None,
            "status": (ProposalStatus.AMBIGUOUS if f.ambiguous else ProposalStatus.PROPOSED).value,
        }
        for f in found
    ]


def _meeting_rows(
    session: Session, ws_id: uuid.UUID, account_id: uuid.UUID, contacts: Sequence[Contact], blocked
) -> list[dict[str, Any]]:
    docs = {
        d.id: d.text
        for d in session.scalars(
            select(Document).where(
                Document.workspace_id == ws_id, Document.account_id == account_id
            )
        )
    }
    if not docs:
        return []
    chunks = [
        meeting_patterns.ChunkRec(
            c.document_id, c.id, c.speaker, c.contact_id, c.char_start, c.char_end, c.text
        )
        for c in session.scalars(
            select(DocumentChunk).where(
                DocumentChunk.workspace_id == ws_id,
                DocumentChunk.document_id.in_(list(docs)),
                DocumentChunk.contact_id.is_not(None),
            )
        )
    ]
    refs = [meeting_patterns.ContactRef(c.id, c.full_name) for c in contacts]
    parents = {c.id: c.reports_to_id for c in contacts}
    links = {c.id: c.reports_to_id for c in contacts}
    rows: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for f in meeting_patterns.extract(chunks, refs, docs):
        key = (f.contact_id, f.kind, f.manager_id)
        if key in seen or key in blocked:
            continue
        rule: str | None = f.pattern
        if f.kind == ProposalKind.REPORTS_TO.value:
            assert f.manager_id is not None
            current = links.get(f.contact_id)
            if current == f.manager_id:
                continue  # already true
            if rules.would_cycle(parents, f.contact_id, f.manager_id):
                continue
            if current is not None:
                rule = CONTRADICTS
        seen.add(key)
        rows.append(
            {
                "kind": f.kind,
                "contact_id": f.contact_id,
                "manager_id": f.manager_id,
                "rule": rule,
                "evidence": dict(f.evidence),
                "candidates": None,
                "status": ProposalStatus.PROPOSED.value,
            }
        )
    return rows


def propose(
    session: Session,
    ws_id: uuid.UUID,
    account_id: uuid.UUID | None,
    origins: Sequence[ProposalOrigin],
) -> dict[str, Any]:
    """(Re)generate proposals for one account, or for every account of the workspace. A rerun
    replaces the proposed and ambiguous proposals of the requested origins; accepted and
    rejected ones are kept. Never touches an existing manager link."""
    if account_id is not None:
        require_account(session, ws_id, account_id)
        account_ids = [account_id]
    else:
        account_ids = list(
            session.scalars(
                select(Account.id).where(Account.workspace_id == ws_id).order_by(Account.id)
            )
        )
    origin_values = sorted({o.value for o in origins})
    run = runs.start_run(
        session,
        RunKind.ORG_RULES,
        ws_id,
        {"account_id": str(account_id) if account_id else None, "origins": origin_values},
    )
    by_kind: Counter[str] = Counter()
    ambiguous = 0
    created = 0
    for acc_id in account_ids:
        contact_service._lock_org_chart(session, acc_id)  # noqa: SLF001
        contacts = contact_service.list_contacts(session, ws_id, acc_id)
        session.execute(
            delete(OrgProposal)
            .where(
                OrgProposal.workspace_id == ws_id,
                OrgProposal.account_id == acc_id,
                OrgProposal.status.in_(_OPEN),
                OrgProposal.origin.in_(origin_values),
            )
            .execution_options(synchronize_session="fetch")
        )
        blocked = _blocked(session, ws_id, acc_id)
        batches: list[tuple[str, list[dict[str, Any]]]] = []
        if ProposalOrigin.RULE.value in origin_values:
            batches.append(
                (ProposalOrigin.RULE.value, _rule_rows(session, ws_id, acc_id, contacts, blocked))
            )
        if ProposalOrigin.MEETING.value in origin_values:
            batches.append(
                (
                    ProposalOrigin.MEETING.value,
                    _meeting_rows(session, ws_id, acc_id, contacts, blocked),
                )
            )
        for origin, rows in batches:
            for row in rows:
                session.add(
                    OrgProposal(
                        workspace_id=ws_id, account_id=acc_id, origin=origin, run_id=run.id, **row
                    )
                )
                created += 1
                by_kind[row["kind"]] += 1
                ambiguous += row["status"] == ProposalStatus.AMBIGUOUS.value
    session.flush()
    out = {
        "run_id": run.id,
        "created": created,
        "by_kind": dict(by_kind),
        "ambiguous": ambiguous,
    }
    runs.finish_run(
        session,
        run,
        RunStatus.SUCCEEDED,
        {k: (str(v) if k == "run_id" else v) for k, v in out.items()},
    )
    return out


def list_proposals(
    session: Session,
    ws_id: uuid.UUID,
    account_id: uuid.UUID,
    status: ProposalStatus | None = None,
) -> list[OrgProposal]:
    require_account(session, ws_id, account_id)
    stmt = select(OrgProposal).where(
        OrgProposal.workspace_id == ws_id, OrgProposal.account_id == account_id
    )
    if status is not None:
        stmt = stmt.where(OrgProposal.status == status.value)
    return list(session.scalars(stmt.order_by(OrgProposal.created_at, OrgProposal.id)))


def contacts_by_id(
    session: Session, ws_id: uuid.UUID, ids: set[uuid.UUID]
) -> dict[uuid.UUID, Contact]:
    if not ids:
        return {}
    return {
        c.id: c
        for c in session.scalars(
            select(Contact).where(Contact.workspace_id == ws_id, Contact.id.in_(ids))
        )
    }


def get_proposal(session: Session, ws_id: uuid.UUID, proposal_id: uuid.UUID) -> OrgProposal:
    return require(session, OrgProposal, ws_id, proposal_id)


def _decide_user(session: Session, ws_id: uuid.UUID, by_id: uuid.UUID | None) -> uuid.UUID | None:
    if by_id is not None:
        require_user(session, ws_id, by_id)
    return by_id


def _open_proposal(session: Session, ws_id: uuid.UUID, proposal_id: uuid.UUID) -> OrgProposal:
    """The proposal, read again after the account's org-chart lock is held, so two concurrent
    decisions run one after the other and the second sees the first one's status."""
    proposal = get_proposal(session, ws_id, proposal_id)
    contact_service._lock_org_chart(session, proposal.account_id)  # noqa: SLF001
    session.refresh(proposal)
    if proposal.status not in _OPEN:
        raise InvalidInputError(f"this proposal is already {proposal.status}")
    return proposal


def accept(
    session: Session,
    ws_id: uuid.UUID,
    proposal_id: uuid.UUID,
    *,
    manager_id: uuid.UUID | None = None,
    by_id: uuid.UUID | None = None,
) -> OrgProposal:
    by = _decide_user(session, ws_id, by_id)
    proposal = _open_proposal(session, ws_id, proposal_id)
    if proposal.kind == ProposalKind.REPORTS_TO.value:
        if proposal.manager_id is None:  # ambiguous: the user picks among the candidates
            if manager_id is None:
                raise InvalidInputError("manager_id is required to pick among the candidates")
            if str(manager_id) not in (proposal.candidates or []):
                raise InvalidInputError("manager_id is not one of the candidates")
            chosen = manager_id
        else:
            if manager_id is not None and manager_id != proposal.manager_id:
                raise InvalidInputError("manager_id differs from the proposed manager")
            chosen = proposal.manager_id
        contact_service.set_reports_to(session, ws_id, proposal.contact_id, chosen)
        contact = require(session, Contact, ws_id, proposal.contact_id)
        contact.reports_to_proposal_id = proposal.id
        proposal.manager_id = chosen
    elif manager_id is not None:
        raise InvalidInputError("manager_id only applies to reports_to proposals")
    proposal.status = ProposalStatus.ACCEPTED.value
    proposal.decided_at = datetime.now(UTC)
    proposal.decided_by_id = by
    session.flush()
    return proposal


def reject(
    session: Session, ws_id: uuid.UUID, proposal_id: uuid.UUID, *, by_id: uuid.UUID | None = None
) -> OrgProposal:
    by = _decide_user(session, ws_id, by_id)
    proposal = _open_proposal(session, ws_id, proposal_id)
    proposal.status = ProposalStatus.REJECTED.value
    proposal.decided_at = datetime.now(UTC)
    proposal.decided_by_id = by
    session.flush()
    return proposal


def chart_annotations(
    session: Session, ws_id: uuid.UUID, account_id: uuid.UUID
) -> tuple[dict[uuid.UUID, tuple[str, uuid.UUID]], dict[uuid.UUID, list[str]]]:
    """({contact: (origin, proposal id)} for links validated from a proposal,
    {contact: accepted signals})."""
    origins: dict[uuid.UUID, tuple[str, uuid.UUID]] = {}
    signals: dict[uuid.UUID, set[str]] = {}
    rows = session.scalars(
        select(OrgProposal).where(
            OrgProposal.workspace_id == ws_id,
            OrgProposal.account_id == account_id,
            OrgProposal.status == ProposalStatus.ACCEPTED.value,
        )
    )
    linked = dict(
        session.execute(
            select(Contact.id, Contact.reports_to_proposal_id).where(
                Contact.workspace_id == ws_id,
                Contact.account_id == account_id,
                Contact.reports_to_id.is_not(None),
                Contact.reports_to_proposal_id.is_not(None),
            )
        ).all()
    )
    for p in rows:
        if p.kind == ProposalKind.REPORTS_TO.value:
            if linked.get(p.contact_id) == p.id:
                origins[p.contact_id] = (p.origin, p.id)
        else:
            signals.setdefault(p.contact_id, set()).add(p.kind)
    return origins, {k: sorted(v) for k, v in signals.items()}
