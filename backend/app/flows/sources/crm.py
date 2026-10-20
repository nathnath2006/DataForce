"""The CRM tables a dataset block can read (docs/M2A-CONTRACT.md section 3).

One SQL query per table, workspace-scoped, counts from grouped subqueries (no N+1). Contacts
never expose enriched emails or mobiles.
"""

from __future__ import annotations

import uuid

import pandas as pd
from sqlalchemy import DateTime, Float, Select, Text, case, cast, exists, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from app.auth import visibility
from app.auth.viewer import Viewer
from app.db.models import (
    Account,
    Activity,
    ActivityParticipant,
    AppUser,
    Comment,
    Company,
    Contact,
    Deal,
    DealStageEvent,
    Document,
    DocumentChunk,
    Note,
    Run,
    Task,
    Theme,
    ThemeAssignment,
)
from app.domain.enums import DealStage, RunKind, RunStatus
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
        ("title_function", "text"),
        ("title_seniority", "text"),
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
    "meetings": [
        ("document_id", "text"),
        ("account_id", "text"),
        ("account_name", "text"),
        ("company_name", "text"),
        ("deal_id", "text"),
        ("meeting_date", "date"),
        ("title", "text"),
        ("n_chunks", "integer"),
        ("language", "text"),
    ],
    "meeting_themes": [
        ("document_id", "text"),
        ("account_id", "text"),
        ("account_name", "text"),
        ("company_name", "text"),
        ("deal_id", "text"),
        ("meeting_date", "date"),
        ("theme", "text"),
        ("theme_kind", "text"),
        ("n_chunks", "integer"),
    ],
    # M4. Workspace-scoped; no body text: only the length of a subject or a title.
    "activities": [
        ("activity_id", "text"),
        ("account_id", "text"),
        ("account_name", "text"),
        ("deal_id", "text"),
        ("kind", "text"),
        ("direction", "text"),
        ("occurred_at", "datetime"),
        ("subject_length", "integer"),
        ("n_participants", "integer"),
        ("author", "text"),
        ("source", "text"),
    ],
    "stage_events": [
        ("event_id", "text"),
        ("deal_id", "text"),
        ("deal_name", "text"),
        ("account_id", "text"),
        ("from_stage", "text"),
        ("to_stage", "text"),
        ("changed_at", "datetime"),
        ("changed_by", "text"),
        ("source", "text"),
    ],
    "tasks": [
        ("task_id", "text"),
        ("deal_id", "text"),
        ("account_id", "text"),
        ("account_name", "text"),
        ("title_length", "integer"),
        ("status", "text"),
        ("source", "text"),
        ("owner", "text"),
        ("due_on", "date"),
        ("created_at", "datetime"),
        ("done_at", "datetime"),
    ],
    "deal_theme_flags": [
        ("deal_id", "text"),
        ("deal_name", "text"),
        ("account_name", "text"),
        ("segment", "text"),
        ("lead_source", "text"),
        ("stage", "text"),
        ("is_closed", "boolean"),
        ("is_won", "boolean"),
        ("amount_eur", "number"),
        ("theme", "text"),
        ("theme_kind", "text"),
        ("has_meeting", "boolean"),
        # null when the deal has no meeting: "not mentioned" would wrongly put deals nobody
        # talked about in the comparison group (the stats block excludes missing groups).
        ("mentioned", "boolean"),
    ],
}


_Timestamp = DateTime(timezone=True)


def _text(col):
    return cast(col, Text)


def _deals_query(ws_id: uuid.UUID, viewer: Viewer | None = None) -> Select:
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
        .where(Deal.workspace_id == ws_id, *visibility.conds(visibility.deals_cond(viewer)))
        .order_by(Deal.created_on, Deal.id)
    )


def _accounts_query(ws_id: uuid.UUID, viewer: Viewer | None = None) -> Select:
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
        .where(Deal.workspace_id == ws_id, *visibility.conds(visibility.deals_cond(viewer)))
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
        .where(
            Account.workspace_id == ws_id,
            *visibility.conds(visibility.in_accounts(viewer, Account.id)),
        )
        .order_by(Account.name, Account.id)
    )


def _contacts_query(ws_id: uuid.UUID, viewer: Viewer | None = None) -> Select:
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
            Contact.title_function.label("title_function"),
            Contact.title_seniority.label("title_seniority"),
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
        .where(
            Contact.workspace_id == ws_id,
            *visibility.conds(visibility.in_accounts(viewer, Contact.account_id)),
        )
        .order_by(Contact.full_name, Contact.id)
    )


def _companies_query(ws_id: uuid.UUID, viewer: Viewer | None = None) -> Select:
    vis_acc = visibility.conds(visibility.in_accounts(viewer, Account.id))
    n_acc = (
        select(Account.company_id, func.count().label("n"))
        .where(Account.workspace_id == ws_id, Account.company_id.is_not(None), *vis_acc)
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
        .where(
            Deal.workspace_id == ws_id,
            Account.company_id.is_not(None),
            *vis_acc,
            *visibility.conds(visibility.deals_cond(viewer)),
        )
        .group_by(Account.company_id)
        .subquery()
    )
    note_agg = (
        select(Account.company_id, func.max(Note.created_at).label("last_note"))
        .select_from(Note)
        .join(Contact, Contact.id == Note.contact_id)
        .join(Account, Account.id == Contact.account_id)
        .where(Note.workspace_id == ws_id, Account.company_id.is_not(None), *vis_acc)
        .group_by(Account.company_id)
        .subquery()
    )
    comment_agg = (
        select(Account.company_id, func.max(Comment.created_at).label("last_comment"))
        .select_from(Comment)
        .join(Account, Account.id == Comment.account_id)
        .where(Comment.workspace_id == ws_id, Account.company_id.is_not(None), *vis_acc)
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
        .where(
            Company.workspace_id == ws_id,
            *visibility.conds(visibility.in_companies(viewer, Company.id)),
        )
        .order_by(Company.name, Company.id)
    )


def _latest_run_id(ws_id: uuid.UUID, viewer: Viewer | None = None):
    """The latest theme run over the viewer's own rows (see services.themes.latest_run)."""
    key = visibility.scope_key(viewer)
    scope = Run.params["scope"].astext
    return (
        select(Run.id)
        .where(
            Run.workspace_id == ws_id,
            Run.kind == RunKind.THEME_ANALYSIS.value,
            Run.status == RunStatus.SUCCEEDED.value,
            or_(scope.is_(None), scope == "all") if key == "all" else scope == key,
        )
        .order_by(Run.started_at.desc(), Run.id)
        .limit(1)
        .scalar_subquery()
    )


def _meetings_query(ws_id: uuid.UUID, viewer: Viewer | None = None) -> Select:
    n_chunks = (
        select(DocumentChunk.document_id, func.count().label("n"))
        .where(DocumentChunk.workspace_id == ws_id)
        .group_by(DocumentChunk.document_id)
        .subquery()
    )
    return (
        select(
            _text(Document.id).label("document_id"),
            _text(Document.account_id).label("account_id"),
            Account.name.label("account_name"),
            Company.name.label("company_name"),
            _text(Document.deal_id).label("deal_id"),
            Document.meeting_date.label("meeting_date"),
            Document.title.label("title"),
            func.coalesce(n_chunks.c.n, 0).label("n_chunks"),
            Document.language.label("language"),
        )
        .join(Account, Account.id == Document.account_id)
        .outerjoin(Company, Company.id == Account.company_id)
        .outerjoin(n_chunks, n_chunks.c.document_id == Document.id)
        .where(
            Document.workspace_id == ws_id,
            *visibility.conds(visibility.in_accounts(viewer, Document.account_id)),
        )
        .order_by(Document.meeting_date, Document.title, Document.id)
    )


def _meeting_themes_query(ws_id: uuid.UUID, viewer: Viewer | None = None) -> Select:
    return (
        select(
            _text(Document.id).label("document_id"),
            _text(Document.account_id).label("account_id"),
            Account.name.label("account_name"),
            Company.name.label("company_name"),
            _text(Document.deal_id).label("deal_id"),
            Document.meeting_date.label("meeting_date"),
            Theme.label.label("theme"),
            Theme.kind.label("theme_kind"),
            func.count().label("n_chunks"),
        )
        .select_from(ThemeAssignment)
        .join(Theme, Theme.id == ThemeAssignment.theme_id)
        .join(DocumentChunk, DocumentChunk.id == ThemeAssignment.chunk_id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(Account, Account.id == Document.account_id)
        .outerjoin(Company, Company.id == Account.company_id)
        .where(
            Theme.workspace_id == ws_id,
            Theme.run_id == _latest_run_id(ws_id, viewer),
            *visibility.conds(visibility.in_accounts(viewer, Document.account_id)),
        )
        .group_by(Document.id, Account.id, Company.id, Theme.id)
        .order_by(Document.meeting_date, Document.id, Theme.seq)
    )


def _deal_theme_flags_query(ws_id: uuid.UUID, viewer: Viewer | None = None) -> Select:
    has_meeting = exists().where(Document.deal_id == Deal.id, Document.workspace_id == ws_id)
    assigned = exists().where(
        ThemeAssignment.theme_id == Theme.id,
        DocumentChunk.id == ThemeAssignment.chunk_id,
        Document.id == DocumentChunk.document_id,
        Document.deal_id == Deal.id,
    )
    mentioned = case((has_meeting, assigned), else_=None)
    return (
        select(
            _text(Deal.id).label("deal_id"),
            Deal.name.label("deal_name"),
            Account.name.label("account_name"),
            Account.segment.label("segment"),
            Deal.lead_source.label("lead_source"),
            Deal.stage.label("stage"),
            Deal.stage.in_(CLOSED).label("is_closed"),
            case(
                (Deal.stage == DealStage.CLOSED_WON.value, literal(True)),
                (Deal.stage == DealStage.CLOSED_LOST.value, literal(False)),
                else_=None,
            ).label("is_won"),
            cast(Deal.amount_eur, Float).label("amount_eur"),
            Theme.label.label("theme"),
            Theme.kind.label("theme_kind"),
            has_meeting.label("has_meeting"),
            mentioned.label("mentioned"),
        )
        .select_from(Deal)
        .join(Account, Account.id == Deal.account_id)
        .join(Theme, Theme.run_id == _latest_run_id(ws_id, viewer))
        .where(
            Deal.workspace_id == ws_id,
            Theme.workspace_id == ws_id,
            *visibility.conds(visibility.deals_cond(viewer)),
        )
        .order_by(Deal.created_on, Deal.id, Theme.seq)
    )


def _activities_query(ws_id: uuid.UUID, viewer: Viewer | None = None) -> Select:
    people = (
        select(ActivityParticipant.activity_id, func.count().label("n"))
        .group_by(ActivityParticipant.activity_id)
        .subquery()
    )
    return (
        select(
            _text(Activity.id).label("activity_id"),
            _text(Activity.account_id).label("account_id"),
            Account.name.label("account_name"),
            _text(Activity.deal_id).label("deal_id"),
            Activity.kind.label("kind"),
            Activity.direction.label("direction"),
            Activity.occurred_at.label("occurred_at"),
            func.char_length(Activity.subject).label("subject_length"),
            func.coalesce(people.c.n, 0).label("n_participants"),
            AppUser.display_name.label("author"),
            Activity.source.label("source"),
        )
        .join(Account, Account.id == Activity.account_id)
        .outerjoin(people, people.c.activity_id == Activity.id)
        .outerjoin(AppUser, AppUser.id == Activity.author_user_id)
        .where(
            Activity.workspace_id == ws_id,
            *visibility.conds(visibility.in_accounts(viewer, Activity.account_id)),
        )
        .order_by(Activity.occurred_at, Activity.id)
    )


def _stage_events_query(ws_id: uuid.UUID, viewer: Viewer | None = None) -> Select:
    return (
        select(
            _text(DealStageEvent.id).label("event_id"),
            _text(DealStageEvent.deal_id).label("deal_id"),
            Deal.name.label("deal_name"),
            _text(Deal.account_id).label("account_id"),
            DealStageEvent.from_stage.label("from_stage"),
            DealStageEvent.to_stage.label("to_stage"),
            DealStageEvent.changed_at.label("changed_at"),
            AppUser.display_name.label("changed_by"),
            DealStageEvent.source.label("source"),
        )
        .join(Deal, Deal.id == DealStageEvent.deal_id)
        .outerjoin(AppUser, AppUser.id == DealStageEvent.changed_by_id)
        .where(
            DealStageEvent.workspace_id == ws_id,
            *visibility.conds(visibility.in_deals(viewer, DealStageEvent.deal_id)),
        )
        .order_by(DealStageEvent.changed_at, DealStageEvent.id)
    )


def _tasks_query(ws_id: uuid.UUID, viewer: Viewer | None = None) -> Select:
    return (
        select(
            _text(Task.id).label("task_id"),
            _text(Task.deal_id).label("deal_id"),
            _text(Task.account_id).label("account_id"),
            Account.name.label("account_name"),
            func.char_length(Task.title).label("title_length"),
            Task.status.label("status"),
            Task.source.label("source"),
            AppUser.display_name.label("owner"),
            Task.due_on.label("due_on"),
            Task.created_at.label("created_at"),
            Task.done_at.label("done_at"),
        )
        .outerjoin(Account, Account.id == Task.account_id)
        .outerjoin(AppUser, AppUser.id == Task.owner_user_id)
        .where(
            Task.workspace_id == ws_id,
            *visibility.conds(visibility.account_or_deal(viewer, Task.account_id, Task.deal_id)),
        )
        .order_by(Task.created_at, Task.id)
    )


_QUERIES = {
    "activities": _activities_query,
    "stage_events": _stage_events_query,
    "tasks": _tasks_query,
    "meetings": _meetings_query,
    "meeting_themes": _meeting_themes_query,
    "deal_theme_flags": _deal_theme_flags_query,
    "deals": _deals_query,
    "accounts": _accounts_query,
    "contacts": _contacts_query,
    "companies": _companies_query,
}


def load_crm_table(
    session: Session,
    ws_id: uuid.UUID,
    table: str,
    max_rows: int,
    viewer: Viewer | None = None,
) -> pd.DataFrame:
    """At most `max_rows` rows of the rows the viewer may see (`None`: all of them);
    `attrs["capped"]` is set when rows were cut."""
    stmt = _QUERIES[table](ws_id, viewer).limit(max_rows + 1)
    names = [name for name, _ in CRM_COLUMNS[table]]
    rows = [tuple(r) for r in session.execute(stmt)]
    capped = len(rows) > max_rows
    df = frame_from_rows(rows[:max_rows], names)
    for name in ("is_closed", "has_meeting"):
        if name in df:
            df[name] = df[name].astype(bool)
    if "mentioned" in df:  # True / False / None (no meeting): keep the missing values
        df["mentioned"] = df["mentioned"].astype(object).where(df["mentioned"].notna(), None)
    for name in ("cycle_days", "employee_count", "subject_length", "title_length"):
        if name in df:  # integers, or floats with NaN when a value is missing (no pd.NA)
            df[name] = pd.to_numeric(df[name])
            if not df[name].isna().any():
                df[name] = df[name].astype("int64")
    for name in ("created_on", "closed_on", "meeting_date", "due_on"):
        if name in df:
            df[name] = pd.to_datetime(df[name])
    if capped:
        df.attrs["capped"] = True
    return df
