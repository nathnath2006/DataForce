"""Org-chart proposals: run the rules / meeting extraction, list, accept, reject."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import APIRouter

from app.api.deps import AppSettings, CurrentViewer, CurrentWorkspace, Db
from app.api.routes.ai import Factory
from app.api.schemas_orgchart import (
    AcceptIn,
    ProposalContact,
    ProposalOut,
    ProposeIn,
    ProposeOut,
    RejectIn,
)
from app.db.models import Contact, OrgProposal
from app.domain.enums import ProposalStatus
from app.services import org_proposals

router = APIRouter(tags=["orgchart"])


def _out(db: Db, ws_id: uuid.UUID, rows: Sequence[OrgProposal]) -> list[ProposalOut]:
    ids: set[uuid.UUID] = set()
    for p in rows:
        ids.add(p.contact_id)
        if p.manager_id:
            ids.add(p.manager_id)
        ids.update(uuid.UUID(c) for c in p.candidates or [])
    people = org_proposals.contacts_by_id(db, ws_id, ids)

    def card(cid: uuid.UUID) -> ProposalContact | None:
        c: Contact | None = people.get(cid)
        return ProposalContact(id=c.id, full_name=c.full_name, title=c.title) if c else None

    out = []
    for p in rows:
        contact = card(p.contact_id)
        assert contact is not None
        out.append(
            ProposalOut(
                id=p.id,
                kind=p.kind,
                origin=p.origin,
                rule=p.rule,
                status=p.status,
                contact=contact,
                manager=card(p.manager_id) if p.manager_id else None,
                candidates=[c for c in (card(uuid.UUID(x)) for x in p.candidates or []) if c],
                evidence=p.evidence,
                created_at=p.created_at,
                decided_at=p.decided_at,
            )
        )
    return out


@router.post("/w/{ws}/orgchart/propose", response_model=ProposeOut)
def propose(
    body: ProposeIn,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    factory: Factory,
    viewer: CurrentViewer,
) -> ProposeOut:
    result = org_proposals.propose(
        db,
        ws.id,
        body.account_id,
        body.origins,
        use_ai=body.use_ai,
        settings=settings,
        factory=factory,
        viewer=viewer,
    )
    db.commit()
    return ProposeOut(**result)


@router.get("/w/{ws}/accounts/{account_id}/org-proposals", response_model=list[ProposalOut])
def list_org_proposals(
    account_id: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    status: ProposalStatus | None = None,
) -> list[ProposalOut]:
    return _out(db, ws.id, org_proposals.list_proposals(db, ws.id, account_id, status, viewer))


@router.post("/w/{ws}/org-proposals/{proposal_id}/accept", response_model=ProposalOut)
def accept(
    proposal_id: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    body: AcceptIn | None = None,
) -> ProposalOut:
    body = body or AcceptIn()
    row = org_proposals.accept(
        db,
        ws.id,
        proposal_id,
        manager_id=body.manager_id,
        by_id=viewer.app_user_id,
        force=body.force,
        viewer=viewer,
    )
    db.commit()
    return _out(db, ws.id, [row])[0]


@router.post("/w/{ws}/org-proposals/{proposal_id}/reject", response_model=ProposalOut)
def reject(
    proposal_id: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    body: RejectIn | None = None,
) -> ProposalOut:
    row = org_proposals.reject(db, ws.id, proposal_id, by_id=viewer.app_user_id, viewer=viewer)
    db.commit()
    return _out(db, ws.id, [row])[0]
