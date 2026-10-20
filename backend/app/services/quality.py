"""Data-quality counts: exact SQL, read-only, one query per check. Segments are exclusive and
add up to the total."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, and_, case, exists, func, or_, select
from sqlalchemy.orm import Session

from app.api.schemas_quality import QualityCheck, QualityOut, QualitySegment
from app.auth import visibility
from app.auth.viewer import Viewer
from app.db.models import Account, Contact, Deal, OrgProposal
from app.domain.enums import OPEN_STAGES, ProposalKind, ProposalStatus, TitleSource

_OPEN = [s.value for s in OPEN_STAGES]


def _count(cond) -> object:
    return func.coalesce(func.sum(case((cond, 1), else_=0)), 0)


def _run(db: Session, stmt: Select, spec: list[tuple[str, str]], cid: str, label: str):
    row = db.execute(stmt).one()
    total, *counts = (int(v) for v in row)
    segs = [
        QualitySegment(kind=k, label=lab, count=n)  # type: ignore[arg-type]
        for (k, lab), n in zip(spec, counts, strict=True)
    ]
    return QualityCheck(id=cid, label=label, total=total, segments=segs)  # type: ignore[arg-type]


def _managers(db: Session, ws: uuid.UUID, viewer: Viewer | None) -> QualityCheck:
    has_sug = exists().where(
        OrgProposal.contact_id == Contact.id,
        OrgProposal.workspace_id == ws,
        OrgProposal.kind == ProposalKind.REPORTS_TO.value,
        OrgProposal.status.in_([ProposalStatus.PROPOSED.value, ProposalStatus.AMBIGUOUS.value]),
    )
    linked = Contact.reports_to_id.is_not(None)
    stmt = select(
        func.count(),
        _count(linked),
        _count(and_(~linked, has_sug)),
        _count(and_(~linked, ~has_sug)),
    ).where(
        Contact.workspace_id == ws,
        *visibility.conds(visibility.in_accounts(viewer, Contact.account_id)),
    )
    spec = [
        ("ok", "Has a manager"),
        ("warn", "No manager, suggestion open"),
        ("unknown", "No manager, no suggestion"),
    ]
    return _run(db, stmt, spec, "managers", "Contacts linked to a manager")


def _titles(db: Session, ws: uuid.UUID, viewer: Viewer | None) -> QualityCheck:
    warn = or_(
        func.coalesce(Contact.title_source, "") == TitleSource.LLM.value,
        Contact.title_flag.is_not(None),
    )
    unknown = and_(
        ~warn,
        or_(
            Contact.title_source.is_(None),
            Contact.title_function.is_(None),
            func.coalesce(Contact.title_function, "") == "unknown",
        ),
    )
    stmt = select(func.count(), _count(~warn & ~unknown), _count(warn), _count(unknown)).where(
        Contact.workspace_id == ws,
        *visibility.conds(visibility.in_accounts(viewer, Contact.account_id)),
    )
    spec = [
        ("ok", "Dictionary or manual"),
        ("warn", "By AI or flagged"),
        ("unknown", "Unknown or missing"),
    ]
    return _run(db, stmt, spec, "titles", "Job titles classified")


def _amounts(db: Session, ws: uuid.UUID, viewer: Viewer | None) -> QualityCheck:
    missing = Deal.amount_eur.is_(None)
    is_open = Deal.stage.in_(_OPEN)
    stmt = select(
        func.count(),
        _count(~missing),
        _count(and_(missing, is_open)),
        _count(and_(missing, ~is_open)),
    ).where(Deal.workspace_id == ws, *visibility.conds(visibility.deals_cond(viewer)))
    spec = [
        ("ok", "Amount set"),
        ("bad", "Missing on an open deal"),
        ("unknown", "Missing on a closed deal"),
    ]
    return _run(db, stmt, spec, "amounts", "Deals with an amount")


def _companies(db: Session, ws: uuid.UUID, viewer: Viewer | None) -> QualityCheck:
    linked = Account.company_id.is_not(None)
    stmt = select(func.count(), _count(linked), _count(~linked)).where(
        Account.workspace_id == ws,
        *visibility.conds(visibility.in_accounts(viewer, Account.id)),
    )
    spec = [("ok", "Linked"), ("unknown", "Not linked")]
    return _run(db, stmt, spec, "companies", "Accounts linked to a company")


def quality_report(db: Session, ws: uuid.UUID, viewer: Viewer | None = None) -> QualityOut:
    return QualityOut(
        checks=[
            _managers(db, ws, viewer),
            _titles(db, ws, viewer),
            _amounts(db, ws, viewer),
            _companies(db, ws, viewer),
        ]
    )
