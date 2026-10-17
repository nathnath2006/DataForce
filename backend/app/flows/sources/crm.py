"""The four CRM tables a dataset block can read (docs/M2A-CONTRACT.md section 3).

One SQL query per table, workspace-scoped, counts from grouped subqueries (no N+1). Contacts
never expose enriched emails or mobiles.
"""

from __future__ import annotations

import uuid

import pandas as pd
from sqlalchemy import DateTime, Float, Select, Text, case, cast, exists, func, literal, select
from sqlalchemy.orm import Session, aliased

from app.db.models import Account, AppUser, Comment, Company, Contact, Deal, Note
from app.domain.enums import DealStage
from app.flows.sources.frame import frame_from_rows

CLOSED = (DealStage.CLOSED_WON.value, DealStage.CLOSED_LOST.value)

CRM_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "deals": [
        ("deal_id", "text"),
        ("deal_name", "text"),
        ("account_id", "text"),
        ("account_name", "text"),
        ("company_name", "text"),
        ("segment", "text"),
        ("industry", "text"),
        ("region", "text"),
        ("country", "text"),
        ("owner", "text"),
        ("lead_source", "text"),
        ("stage", "text"),
        ("is_closed", "boolean"),
        ("is_won", "boolean"),
        ("amount_eur", "number"),
        ("created_on", "date"),
        ("closed_on", "date"),
        ("cycle_days", "integer"),
    ],
    "accounts": [
        ("account_id", "text"),
        ("account_name", "text"),
        ("company_name", "text"),
        ("domain", "text"),
        ("industry", "text"),
        ("segment", "text"),
        ("employee_count", "integer"),
        ("region", "text"),
        ("country", "text"),
        ("n_contacts", "integer"),
        ("n_deals", "integer"),
        ("n_open_deals", "integer"),
        ("n_won", "integer"),
        ("n_lost", "integer"),
        ("won_amount_eur", "number"),
    ],
    "contacts": [
        ("contact_id", "text"),
        ("full_name", "text"),
        ("title", "text"),
        ("account_name", "text"),
        ("company_name", "text"),
        ("reports_to_name", "text"),
        ("n_direct_reports", "integer"),
        ("n_notes", "integer"),
    ],
    "companies": [
        ("company_id", "text"),
        ("company_name", "text"),
        ("siren", "text"),
        ("city", "text"),
        ("postal_code", "text"),
        ("naf_code", "text"),
        ("size_bracket", "text"),
        ("category", "text"),
        ("n_accounts", "integer"),
        ("n_deals", "integer"),
        ("last_interaction", "datetime"),
    ],
}


_Timestamp = DateTime(timezone=True)


def _text(col):
    return cast(col, Text)


def _deals_query(ws_id: uuid.UUID) -> Select:
    closed = Deal.stage.in_(CLOSED)
    return (
        select(
            _text(Deal.id).label("deal_id"),
            Deal.name.label("deal_name"),
            _text(Deal.account_id).label("account_id"),
            Account.name.label("account_name"),
            Company.name.label("company_name"),
            Account.segment.label("segment"),
            Account.industry.label("industry"),
            Account.region.label("region"),
            Account.country.label("country"),
            AppUser.display_name.label("owner"),
            Deal.lead_source.label("lead_source"),
            Deal.stage.label("stage"),
            closed.label("is_closed"),
            case(
                (Deal.stage == DealStage.CLOSED_WON.value, literal(True)),
                (Deal.stage == DealStage.CLOSED_LOST.value, literal(False)),
                else_=None,
            ).label("is_won"),
            cast(Deal.amount_eur, Float).label("amount_eur"),
            Deal.created_on.label("created_on"),
            Deal.closed_on.label("closed_on"),
            (Deal.closed_on - Deal.created_on).label("cycle_days"),
        )
        .join(Account, Account.id == Deal.account_id)
        .outerjoin(Company, Company.id == Account.company_id)
        .outerjoin(AppUser, AppUser.id == Deal.owner_id)
        .where(Deal.workspace_id == ws_id)
        .order_by(Deal.created_on, Deal.id)
    )


def _accounts_query(ws_id: uuid.UUID) -> Select:
    n_contacts = (
        select(Contact.account_id, func.count().label("n"))
        .where(Contact.workspace_id == ws_id)
        .group_by(Contact.account_id)
        .subquery()
    )
    won = Deal.stage == DealStage.CLOSED_WON.value
    lost = Deal.stage == DealStage.CLOSED_LOST.value
    deal_agg = (
        select(
            Deal.account_id,
            func.count().label("n_deals"),
            func.count().filter(~Deal.stage.in_(CLOSED)).label("n_open"),
            func.count().filter(won).label("n_won"),
            func.count().filter(lost).label("n_lost"),
            func.coalesce(func.sum(Deal.amount_eur).filter(won), 0).label("won_amount"),
        )
        .where(Deal.workspace_id == ws_id)
        .group_by(Deal.account_id)
        .subquery()
    )
    return (
        select(
            _text(Account.id).label("account_id"),
            Account.name.label("account_name"),
            Company.name.label("company_name"),
            Account.domain.label("domain"),
            Account.industry.label("industry"),
            Account.segment.label("segment"),
            Account.employee_count.label("employee_count"),
            Account.region.label("region"),
            Account.country.label("country"),
            func.coalesce(n_contacts.c.n, 0).label("n_contacts"),
            func.coalesce(deal_agg.c.n_deals, 0).label("n_deals"),
            func.coalesce(deal_agg.c.n_open, 0).label("n_open_deals"),
            func.coalesce(deal_agg.c.n_won, 0).label("n_won"),
            func.coalesce(deal_agg.c.n_lost, 0).label("n_lost"),
            cast(func.coalesce(deal_agg.c.won_amount, 0), Float).label("won_amount_eur"),
        )
        .outerjoin(Company, Company.id == Account.company_id)
        .outerjoin(n_contacts, n_contacts.c.account_id == Account.id)
        .outerjoin(deal_agg, deal_agg.c.account_id == Account.id)
        .where(Account.workspace_id == ws_id)
        .order_by(Account.name, Account.id)
    )


def _contacts_query(ws_id: uuid.UUID) -> Select:
    boss = aliased(Contact)
    reports = (
        select(Contact.reports_to_id.label("boss_id"), func.count().label("n"))
        .where(Contact.workspace_id == ws_id, Contact.reports_to_id.is_not(None))
        .group_by(Contact.reports_to_id)
        .subquery()
    )
    newer = aliased(Note)
    notes = (
        select(Note.contact_id, func.count().label("n"))
        .where(
            Note.workspace_id == ws_id,
            Note.deleted_at.is_(None),
            ~exists().where(newer.corrects_id == Note.id),  # only the current version
        )
        .group_by(Note.contact_id)
        .subquery()
    )
    return (
        select(
            _text(Contact.id).label("contact_id"),
            Contact.full_name.label("full_name"),
            Contact.title.label("title"),
            Account.name.label("account_name"),
            Company.name.label("company_name"),
            boss.full_name.label("reports_to_name"),
            func.coalesce(reports.c.n, 0).label("n_direct_reports"),
            func.coalesce(notes.c.n, 0).label("n_notes"),
        )
        .join(Account, Account.id == Contact.account_id)
        .outerjoin(Company, Company.id == Account.company_id)
        .outerjoin(boss, boss.id == Contact.reports_to_id)
        .outerjoin(reports, reports.c.boss_id == Contact.id)
        .outerjoin(notes, notes.c.contact_id == Contact.id)
        .where(Contact.workspace_id == ws_id)
        .order_by(Contact.full_name, Contact.id)
    )


def _companies_query(ws_id: uuid.UUID) -> Select:
    n_acc = (
        select(Account.company_id, func.count().label("n"))
        .where(Account.workspace_id == ws_id, Account.company_id.is_not(None))
        .group_by(Account.company_id)
        .subquery()
    )
    deal_agg = (
        select(
            Account.company_id,
            func.count().label("n"),
            func.max(
                func.greatest(cast(Deal.created_on, _Timestamp), cast(Deal.closed_on, _Timestamp))
            ).label("last_deal"),
        )
        .join(Account, Account.id == Deal.account_id)
        .where(Deal.workspace_id == ws_id, Account.company_id.is_not(None))
        .group_by(Account.company_id)
        .subquery()
    )
    note_agg = (
        select(Account.company_id, func.max(Note.created_at).label("last_note"))
        .select_from(Note)
        .join(Contact, Contact.id == Note.contact_id)
        .join(Account, Account.id == Contact.account_id)
        .where(Note.workspace_id == ws_id, Account.company_id.is_not(None))
        .group_by(Account.company_id)
        .subquery()
    )
    comment_agg = (
        select(Account.company_id, func.max(Comment.created_at).label("last_comment"))
        .select_from(Comment)
        .join(Account, Account.id == Comment.account_id)
        .where(Comment.workspace_id == ws_id, Account.company_id.is_not(None))
        .group_by(Account.company_id)
        .subquery()
    )
    return (
        select(
            _text(Company.id).label("company_id"),
            Company.name.label("company_name"),
            Company.siren.label("siren"),
            Company.city.label("city"),
            Company.postal_code.label("postal_code"),
            Company.naf_code.label("naf_code"),
            Company.size_bracket.label("size_bracket"),
            Company.category.label("category"),
            func.coalesce(n_acc.c.n, 0).label("n_accounts"),
            func.coalesce(deal_agg.c.n, 0).label("n_deals"),
            func.greatest(
                deal_agg.c.last_deal, note_agg.c.last_note, comment_agg.c.last_comment
            ).label("last_interaction"),
        )
        .outerjoin(n_acc, n_acc.c.company_id == Company.id)
        .outerjoin(deal_agg, deal_agg.c.company_id == Company.id)
        .outerjoin(note_agg, note_agg.c.company_id == Company.id)
        .outerjoin(comment_agg, comment_agg.c.company_id == Company.id)
        .where(Company.workspace_id == ws_id)
        .order_by(Company.name, Company.id)
    )


_QUERIES = {
    "deals": _deals_query,
    "accounts": _accounts_query,
    "contacts": _contacts_query,
    "companies": _companies_query,
}


def load_crm_table(session: Session, ws_id: uuid.UUID, table: str, max_rows: int) -> pd.DataFrame:
    """At most `max_rows` rows; `attrs["capped"]` is set when rows were cut."""
    stmt = _QUERIES[table](ws_id).limit(max_rows + 1)
    names = [name for name, _ in CRM_COLUMNS[table]]
    rows = [tuple(r) for r in session.execute(stmt)]
    capped = len(rows) > max_rows
    df = frame_from_rows(rows[:max_rows], names)
    if "is_closed" in df:
        df["is_closed"] = df["is_closed"].astype(bool)
    for name in ("cycle_days", "employee_count"):
        if name in df:  # integers, or floats with NaN when a value is missing (no pd.NA)
            df[name] = pd.to_numeric(df[name])
            if not df[name].isna().any():
                df[name] = df[name].astype("int64")
    for name in ("created_on", "closed_on"):
        if name in df:
            df[name] = pd.to_datetime(df[name])
    if capped:
        df.attrs["capped"] = True
    return df
