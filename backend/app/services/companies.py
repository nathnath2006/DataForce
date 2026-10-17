"""Companies: a legal entity or group that one or more accounts belong to (M2a)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, case, cast, func, or_, select, union_all
from sqlalchemy.orm import Session

from app.db.models import Account, Comment, Company, Contact, Deal, Note
from app.domain.enums import CLOSED_STAGES, DealStage
from app.registry.client import RegistryCompany
from app.services._common import (
    LIKE_ESCAPE,
    get_scoped,
    like_contains,
    require,
    require_account,
    require_workspace,
)
from app.services.errors import AlreadyExistsError, InvalidInputError
from app.services.textclean import scrub_optional, scrub_text

EXCERPT_CHARS = 200
_UPDATABLE = ("name", "domain", "address_line", "postal_code", "city", "country")


def require_company(session: Session, ws_id: uuid.UUID, company_id: uuid.UUID) -> Company:
    return require(session, Company, ws_id, company_id)


def get_company(session: Session, ws_id: uuid.UUID, company_id: uuid.UUID) -> Company | None:
    return get_scoped(session, Company, ws_id, company_id)


def _siren_taken(session: Session, ws_id: uuid.UUID, siren: str, *, except_id=None) -> bool:
    stmt = select(Company.id).where(Company.workspace_id == ws_id, Company.siren == siren)
    if except_id is not None:
        stmt = stmt.where(Company.id != except_id)
    return session.scalar(stmt.limit(1)) is not None


def create_company(
    session: Session,
    ws_id: uuid.UUID,
    *,
    name: str,
    siren: str | None = None,
    domain: str | None = None,
    address_line: str | None = None,
    postal_code: str | None = None,
    city: str | None = None,
    country: str | None = None,
    source: str = "manual",
    naf_code: str | None = None,
    legal_category: str | None = None,
    size_bracket: str | None = None,
    category: str | None = None,
    registry_checked_at: datetime | None = None,
) -> Company:
    require_workspace(session, ws_id)
    name = scrub_text(name).strip()
    if not name:
        raise InvalidInputError("name cannot be empty")
    if siren is not None and _siren_taken(session, ws_id, siren):
        raise AlreadyExistsError("a company with this SIREN already exists in this workspace")
    company = Company(
        workspace_id=ws_id,
        name=name,
        siren=siren,
        domain=scrub_optional(domain),
        address_line=scrub_optional(address_line),
        postal_code=scrub_optional(postal_code),
        city=scrub_optional(city),
        country=scrub_optional(country.upper()) if country else None,
        naf_code=naf_code,
        legal_category=legal_category,
        size_bracket=size_bracket,
        category=category,
        source=source,
        registry_checked_at=registry_checked_at,
    )
    session.add(company)
    session.flush()
    return company


def create_from_registry(session: Session, ws_id: uuid.UUID, record: RegistryCompany) -> Company:
    """The user chose to add this registry company: its data is stored (sole trader's name too)."""
    return create_company(
        session,
        ws_id,
        name=record.name,
        siren=record.siren,
        address_line=record.address_line,
        postal_code=record.postal_code,
        city=record.city,
        country="FR",
        source="registry",
        naf_code=record.naf_code,
        legal_category=record.legal_category,
        size_bracket=record.size_bracket,
        category=record.category,
        registry_checked_at=datetime.now(UTC),
    )


def apply_registry(session: Session, company: Company, record: RegistryCompany) -> Company:
    company.name = record.name
    company.address_line = record.address_line
    company.postal_code = record.postal_code
    company.city = record.city
    company.naf_code = record.naf_code
    company.legal_category = record.legal_category
    company.size_bracket = record.size_bracket
    company.category = record.category
    company.registry_checked_at = datetime.now(UTC)
    session.flush()
    return company


def update_company(
    session: Session, ws_id: uuid.UUID, company_id: uuid.UUID, changes: dict[str, Any]
) -> Company:
    company = require_company(session, ws_id, company_id)
    unknown = set(changes) - set(_UPDATABLE)
    if unknown:
        raise InvalidInputError(f"cannot update: {', '.join(sorted(unknown))}")
    for key, value in changes.items():
        if key == "name":
            value = scrub_text(value).strip() if value is not None else None
            if not value:
                raise InvalidInputError("name cannot be empty")
        elif key == "country":
            value = scrub_optional(value.upper()) if value else None
        elif isinstance(value, str):
            value = scrub_optional(value)
        setattr(company, key, value)
    session.flush()
    return company


def delete_company(session: Session, ws_id: uuid.UUID, company_id: uuid.UUID) -> None:
    """Deletes the company; its accounts are kept and unlinked (FK SET NULL)."""
    company = require_company(session, ws_id, company_id)
    session.delete(company)  # no ORM relationship: the database sets account.company_id to NULL
    session.flush()
    session.expire_all()


def link_account(
    session: Session, ws_id: uuid.UUID, account_id: uuid.UUID, company_id: uuid.UUID | None
) -> Account:
    account = require_account(session, ws_id, account_id)
    if company_id is not None:
        require_company(session, ws_id, company_id)
    account.company_id = company_id
    session.flush()
    return account


def _match(term: str):
    pattern = like_contains(term)
    cond = [
        Company.name.ilike(pattern, escape=LIKE_ESCAPE),
        Company.domain.ilike(pattern, escape=LIKE_ESCAPE),
        Company.siren.ilike(pattern, escape=LIKE_ESCAPE),
    ]
    return or_(*cond)


def list_companies_page(
    session: Session,
    ws_id: uuid.UUID,
    *,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Company], int]:
    cond = [Company.workspace_id == ws_id]
    if q:
        cond.append(_match(q))
    total = session.scalar(select(func.count()).select_from(Company).where(*cond)) or 0
    stmt = select(Company).where(*cond).order_by(Company.name, Company.id)
    return list(session.scalars(stmt.limit(limit).offset(offset))), total


def find_by_sirens(session: Session, ws_id: uuid.UUID, sirens: list[str]) -> dict[str, uuid.UUID]:
    if not sirens:
        return {}
    rows = session.execute(
        select(Company.siren, Company.id).where(
            Company.workspace_id == ws_id, Company.siren.in_(sirens)
        )
    )
    return {s: i for s, i in rows}


def lookup_accounts_without_company(
    session: Session, ws_id: uuid.UUID, q: str, limit: int = 20
) -> list[Account]:
    pattern = like_contains(q)
    stmt = (
        select(Account)
        .where(
            Account.workspace_id == ws_id,
            Account.company_id.is_(None),
            or_(
                Account.name.ilike(pattern, escape=LIKE_ESCAPE),
                Account.domain.ilike(pattern, escape=LIKE_ESCAPE),
            ),
        )
        .order_by(Account.name, Account.id)
        .limit(limit)
    )
    return list(session.scalars(stmt))


def company_names(session: Session, ws_id: uuid.UUID, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = session.execute(
        select(Company.id, Company.name).where(Company.workspace_id == ws_id, Company.id.in_(ids))
    )
    return dict(rows.all())


# --- aggregates -----------------------------------------------------------------------------
def _interaction_union(ws_id: uuid.UUID):
    """(account_id, at) rows: deal created / closed, current notes of the account's contacts,
    comments. Dates are computed in SQL."""
    parts = [
        select(Deal.account_id.label("account_id"), Deal.created_on.label("at")).where(
            Deal.workspace_id == ws_id
        ),
        select(Deal.account_id, Deal.closed_on).where(
            Deal.workspace_id == ws_id, Deal.closed_on.is_not(None)
        ),
        select(Contact.account_id, cast(Note.created_at, Date))
        .join(Contact, Contact.id == Note.contact_id)
        .where(Note.workspace_id == ws_id, Note.deleted_at.is_(None)),
        select(Comment.account_id, cast(Comment.created_at, Date)).where(
            Comment.workspace_id == ws_id, Comment.deleted_at.is_(None)
        ),
    ]
    return union_all(*parts).subquery("interactions")


def account_last_interaction(
    session: Session, ws_id: uuid.UUID, account_ids: list[uuid.UUID]
) -> dict[uuid.UUID, date]:
    if not account_ids:
        return {}
    u = _interaction_union(ws_id)
    rows = session.execute(
        select(u.c.account_id, func.max(u.c.at))
        .where(u.c.account_id.in_(account_ids))
        .group_by(u.c.account_id)
    )
    return {a: d for a, d in rows if d is not None}


def company_stats(
    session: Session, ws_id: uuid.UUID, company_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Per company: n_accounts, n_contacts, n_deals, n_open_deals, won_amount_eur,
    last_interaction, interacted. Grouped SQL aggregates, no per-row query."""
    out: dict[uuid.UUID, dict[str, Any]] = {
        cid: {
            "n_accounts": 0,
            "n_contacts": 0,
            "n_deals": 0,
            "n_open_deals": 0,
            "won_amount_eur": Decimal(0),
            "last_interaction": None,
            "interacted": False,
        }
        for cid in company_ids
    }
    if not company_ids:
        return out
    for cid, n in session.execute(
        select(Account.company_id, func.count(Account.id))
        .where(Account.workspace_id == ws_id, Account.company_id.in_(company_ids))
        .group_by(Account.company_id)
    ):
        out[cid]["n_accounts"] = n
    for cid, n in session.execute(
        select(Account.company_id, func.count(Contact.id))
        .join(Contact, Contact.account_id == Account.id)
        .where(Account.workspace_id == ws_id, Account.company_id.in_(company_ids))
        .group_by(Account.company_id)
    ):
        out[cid]["n_contacts"] = n
    closed = [s.value for s in CLOSED_STAGES]
    for cid, n, n_open, won in session.execute(
        select(
            Account.company_id,
            func.count(Deal.id),
            func.coalesce(func.sum(case((Deal.stage.in_(closed), 0), else_=1)), 0),
            func.coalesce(
                func.sum(
                    case((Deal.stage == DealStage.CLOSED_WON.value, Deal.amount_eur), else_=0)
                ),
                0,
            ),
        )
        .join(Deal, Deal.account_id == Account.id)
        .where(Account.workspace_id == ws_id, Account.company_id.in_(company_ids))
        .group_by(Account.company_id)
    ):
        out[cid].update(n_deals=n, n_open_deals=int(n_open), won_amount_eur=Decimal(won))
    u = _interaction_union(ws_id)
    for cid, last in session.execute(
        select(Account.company_id, func.max(u.c.at))
        .join(u, u.c.account_id == Account.id)
        .where(Account.workspace_id == ws_id, Account.company_id.in_(company_ids))
        .group_by(Account.company_id)
    ):
        out[cid]["last_interaction"] = last
        out[cid]["interacted"] = last is not None
    return out


def _excerpt(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= EXCERPT_CHARS else text[: EXCERPT_CHARS - 1] + "…"


def company_360_parts(session: Session, ws_id: uuid.UUID, company_id: uuid.UUID) -> dict:
    """Accounts, contacts (<= 200), deals (<= 500) and activity (<= 50, newest first)."""
    accts = list(
        session.scalars(
            select(Account)
            .where(Account.workspace_id == ws_id, Account.company_id == company_id)
            .order_by(Account.name, Account.id)
        )
    )
    ids = [a.id for a in accts]
    names = {a.id: a.name for a in accts}
    contacts_rows: list[Contact] = []
    deal_rows: list[Deal] = []
    activity: list[dict[str, Any]] = []
    if ids:
        contacts_rows = list(
            session.scalars(
                select(Contact)
                .where(Contact.workspace_id == ws_id, Contact.account_id.in_(ids))
                .order_by(Contact.full_name, Contact.id)
                .limit(200)
            )
        )
        deal_rows = list(
            session.scalars(
                select(Deal)
                .where(Deal.workspace_id == ws_id, Deal.account_id.in_(ids))
                .order_by(Deal.created_on.desc(), Deal.id)
                .limit(500)
            )
        )
        for d in session.scalars(
            select(Deal)
            .where(Deal.workspace_id == ws_id, Deal.account_id.in_(ids))
            .order_by(Deal.created_on.desc())
            .limit(50)
        ):
            activity.append(
                dict(kind="deal_created", at=d.created_on, account_id=d.account_id,
                     deal_id=d.id, title=f"Deal created: {d.name}", excerpt=None)
            )  # fmt: skip
        for d in session.scalars(
            select(Deal)
            .where(
                Deal.workspace_id == ws_id, Deal.account_id.in_(ids), Deal.closed_on.is_not(None)
            )
            .order_by(Deal.closed_on.desc())
            .limit(50)
        ):
            activity.append(
                dict(kind="deal_closed", at=d.closed_on, account_id=d.account_id,
                     deal_id=d.id, title=f"Deal {d.stage}: {d.name}", excerpt=None)
            )  # fmt: skip
        for n, cid, aid, cname in session.execute(
            select(Note, Contact.id, Contact.account_id, Contact.full_name)
            .join(Contact, Contact.id == Note.contact_id)
            .where(
                Note.workspace_id == ws_id,
                Contact.account_id.in_(ids),
                Note.deleted_at.is_(None),
                Note.id.not_in(select(Note.corrects_id).where(Note.corrects_id.is_not(None))),
            )
            .order_by(Note.created_at.desc())
            .limit(50)
        ):
            activity.append(
                dict(kind="note", at=n.created_at, account_id=aid, contact_id=cid,
                     title=f"Note on {cname}", excerpt=_excerpt(n.body))
            )  # fmt: skip
        for c in session.scalars(
            select(Comment)
            .where(
                Comment.workspace_id == ws_id,
                Comment.account_id.in_(ids),
                Comment.deleted_at.is_(None),
            )
            .order_by(Comment.created_at.desc())
            .limit(50)
        ):
            activity.append(
                dict(kind="comment", at=c.created_at, account_id=c.account_id,
                     title=f"Comment on {names[c.account_id]}", excerpt=_excerpt(c.body))
            )  # fmt: skip

    def _key(item: dict[str, Any]) -> datetime:
        at = item["at"]
        if isinstance(at, datetime):
            return at if at.tzinfo else at.replace(tzinfo=UTC)
        return datetime(at.year, at.month, at.day, tzinfo=UTC)

    activity.sort(key=_key, reverse=True)
    return {
        "accounts": accts,
        "contacts": contacts_rows,
        "deals": deal_rows,
        "activity": activity[:50],
    }
