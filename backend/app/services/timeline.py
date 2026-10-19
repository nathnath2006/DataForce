"""The vertical chronology of a deal or an account (M4): stage changes, activities, notes,
comments, meetings (title and date only) and tasks, merged and sorted newest first.

Text written by customers or reps is data: every summary comes with `summary_untrusted`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, aliased

from app.db.models import (
    Activity,
    Comment,
    Contact,
    DealStageEvent,
    Document,
    Note,
    Task,
)
from app.services import activities as activity_svc
from app.services import users
from app.services._common import require_account, require_deal
from app.services.errors import InvalidInputError

SUMMARY_MAX = 200
MAX_LIMIT = 200
KINDS = ("stage", "call", "email", "meeting", "other", "note", "comment", "task")
_SLACK = 30  # extra rows per source, to skip those already shown when a cursor ties


@dataclass
class Item:
    id: str  # "<source>:<uuid>"
    kind: str
    at: datetime
    title: str
    summary: str | None = None
    summary_untrusted: bool = False
    title_untrusted: bool = False  # the title is rep or customer text
    author_name: str | None = None
    refs: dict[str, Any] = field(default_factory=dict)


def short(text: str | None) -> str | None:
    if not text:
        return None
    flat = " ".join(text.split())
    return flat if len(flat) <= SUMMARY_MAX else flat[: SUMMARY_MAX - 1] + "…"


def _utc(d: date) -> datetime:
    return datetime.combine(d, time(12, 0), tzinfo=UTC)


def encode_cursor(item: Item) -> str:
    return f"{item.at.astimezone(UTC).isoformat()}|{item.id}"


def decode_cursor(raw: str) -> tuple[datetime, str]:
    try:
        at, _, ident = raw.partition("|")
        when = datetime.fromisoformat(at)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return when, ident
    except (ValueError, TypeError, OverflowError) as exc:
        raise InvalidInputError("invalid cursor") from exc


def _key(item: Item) -> tuple[datetime, str]:
    return (item.at, item.id)


def _stage_items(session, ws_id, deal_ids, account_id, before, n) -> list[Item]:
    from app.db.models import Deal

    stmt = select(DealStageEvent, Deal.name).join(Deal, Deal.id == DealStageEvent.deal_id)
    stmt = stmt.where(DealStageEvent.workspace_id == ws_id)
    stmt = stmt.where(
        DealStageEvent.deal_id.in_(deal_ids)
        if deal_ids is not None
        else Deal.account_id == account_id
    )
    if before:
        stmt = stmt.where(DealStageEvent.changed_at <= before)
    rows = session.execute(stmt.order_by(DealStageEvent.changed_at.desc()).limit(n)).all()
    names = users.user_names(
        session, ws_id, [e.changed_by_id for e, _ in rows if e.changed_by_id is not None]
    )
    out = []
    for e, deal_name in rows:
        label = f"{(e.from_stage or 'new').replace('_', ' ')} → {e.to_stage.replace('_', ' ')}"
        out.append(
            Item(
                id=f"stage:{e.id}",
                kind="stage",
                at=e.changed_at,
                title=f"Stage: {label}",
                author_name=names.get(e.changed_by_id) if e.changed_by_id else None,
                refs={"deal_id": str(e.deal_id), "deal_name": deal_name, "event_id": str(e.id)},
            )
        )
    return out


def _activity_items(session, ws_id, deal_id, account_id, before, n) -> list[Item]:
    stmt = select(Activity).where(Activity.workspace_id == ws_id)
    stmt = stmt.where(
        Activity.deal_id == deal_id if deal_id is not None else Activity.account_id == account_id
    )
    if before:
        stmt = stmt.where(Activity.occurred_at <= before)
    rows = list(session.scalars(stmt.order_by(Activity.occurred_at.desc()).limit(n)))
    names = users.user_names(
        session, ws_id, [a.author_user_id for a in rows if a.author_user_id is not None]
    )
    people = activity_svc.participants_of(session, ws_id, [a.id for a in rows])
    out = []
    for a in rows:
        kind = a.kind if a.kind in ("call", "email", "meeting") else "other"
        who = [name for _, name in people.get(a.id, [])]
        out.append(
            Item(
                id=f"activity:{a.id}",
                kind=kind,
                at=a.occurred_at,
                title=a.subject,
                title_untrusted=True,
                summary=short(a.body),
                summary_untrusted=a.body is not None,
                author_name=names.get(a.author_user_id) if a.author_user_id else None,
                refs={
                    "activity_id": str(a.id),
                    "deal_id": str(a.deal_id) if a.deal_id else None,
                    "direction": a.direction,
                    "source": a.source,
                    "participants": who,
                },
            )
        )
    return out


def _note_items(session, ws_id, account_id, before, n) -> list[Item]:
    newer = aliased(Note)
    stmt = (
        select(Note, Contact.full_name, Contact.id)
        .join(Contact, Contact.id == Note.contact_id)
        .where(
            Note.workspace_id == ws_id,
            Contact.account_id == account_id,
            Note.deleted_at.is_(None),
            ~exists().where(newer.corrects_id == Note.id),
        )
    )
    if before:
        stmt = stmt.where(Note.created_at <= before)
    rows = session.execute(stmt.order_by(Note.created_at.desc()).limit(n)).all()
    names = users.user_names(session, ws_id, [r.author_id for r, _, _ in rows if r.author_id])
    return [
        Item(
            id=f"note:{r.id}",
            kind="note",
            at=r.created_at,
            title=f"Note on {contact_name}",
            title_untrusted=True,
            summary=short(r.body),
            summary_untrusted=True,
            author_name=names.get(r.author_id) if r.author_id else None,
            refs={"note_id": str(r.id), "contact_id": str(cid)},
        )
        for r, contact_name, cid in rows
    ]


def _comment_items(session, ws_id, account_id, before, n) -> list[Item]:
    newer = aliased(Comment)
    stmt = select(Comment).where(
        Comment.workspace_id == ws_id,
        Comment.account_id == account_id,
        Comment.deleted_at.is_(None),
        ~exists().where(newer.corrects_id == Comment.id),
    )
    if before:
        stmt = stmt.where(Comment.created_at <= before)
    rows = list(session.scalars(stmt.order_by(Comment.created_at.desc()).limit(n)))
    names = users.user_names(session, ws_id, [r.author_id for r in rows if r.author_id])
    return [
        Item(
            id=f"comment:{r.id}",
            kind="comment",
            at=r.created_at,
            title="Comment on the account",
            summary=short(r.body),
            summary_untrusted=True,
            author_name=names.get(r.author_id) if r.author_id else None,
            refs={"comment_id": str(r.id)},
        )
        for r in rows
    ]


def _document_items(session, ws_id, deal_id, account_id, before, n) -> list[Item]:
    stmt = select(
        Document.id, Document.title, Document.meeting_date, Document.created_at, Document.deal_id
    ).where(Document.workspace_id == ws_id, Document.account_id == account_id)
    if deal_id is not None:
        stmt = stmt.where(Document.deal_id == deal_id)
    rows = session.execute(stmt).all()  # a handful per account; text is never loaded
    out = []
    for did, title, meeting_date, created_at, d_deal in rows:
        at = _utc(meeting_date) if meeting_date else created_at
        if before and at > before:
            continue
        out.append(
            Item(
                id=f"document:{did}",
                kind="meeting",
                at=at,
                title=title,
                title_untrusted=True,
                refs={
                    "document_id": str(did),
                    "deal_id": str(d_deal) if d_deal else None,
                    "transcript": True,
                },
            )
        )
    out.sort(key=_key, reverse=True)
    return out[:n]


def _task_items(session, ws_id, deal_id, account_id, before, n) -> list[Item]:
    at_col = Task.done_at
    stmt = select(Task).where(Task.workspace_id == ws_id)
    stmt = stmt.where(
        Task.deal_id == deal_id if deal_id is not None else Task.account_id == account_id
    )
    if before:
        stmt = stmt.where(
            or_(and_(at_col.is_not(None), at_col <= before), Task.created_at <= before)
        )
    rows = list(session.scalars(stmt.order_by(Task.created_at.desc()).limit(n * 2)))
    names = users.user_names(session, ws_id, [r.owner_user_id for r in rows if r.owner_user_id])
    out = []
    for t in rows:
        at = t.done_at or t.created_at
        verb = {"done": "done", "dismissed": "dismissed", "suggested": "suggested"}.get(
            t.status, "open"
        )
        out.append(
            Item(
                id=f"task:{t.id}",
                kind="task",
                at=at,
                title=f"Task {verb}: {t.title}",
                title_untrusted=True,
                author_name=names.get(t.owner_user_id) if t.owner_user_id else None,
                refs={
                    "task_id": str(t.id),
                    "status": t.status,
                    "due_on": t.due_on.isoformat() if t.due_on else None,
                    "deal_id": str(t.deal_id) if t.deal_id else None,
                },
            )
        )
    return out


def build_timeline(
    session: Session,
    ws_id: uuid.UUID,
    *,
    deal_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    kinds: set[str] | None = None,
    limit: int = 50,
    before: str | None = None,
) -> tuple[list[Item], str | None]:
    """(items newest first, cursor for the next page or None). Exactly one of deal_id and
    account_id. A deal's timeline also carries its account's notes and comments."""
    if (deal_id is None) == (account_id is None):
        raise InvalidInputError("give a deal or an account")
    if kinds is not None and not kinds <= set(KINDS):
        raise InvalidInputError(f"unknown kind; use {', '.join(KINDS)}")
    limit = max(1, min(limit, MAX_LIMIT))
    if deal_id is not None:
        deal = require_deal(session, ws_id, deal_id)
        account = deal.account_id
        deal_ids: list[uuid.UUID] | None = [deal.id]
    else:
        require_account(session, ws_id, account_id)  # type: ignore[arg-type]
        account = account_id  # type: ignore[assignment]
        deal_ids = None
    cursor = decode_cursor(before) if before else None
    when = cursor[0] if cursor else None
    n = limit + 1 + _SLACK

    def want(*names: str) -> bool:
        return kinds is None or any(k in kinds for k in names)

    items: list[Item] = []
    if want("stage"):
        items += _stage_items(session, ws_id, deal_ids, account, when, n)
    if want("call", "email", "meeting", "other"):
        items += _activity_items(session, ws_id, deal_id, account, when, n)
    if want("note"):
        items += _note_items(session, ws_id, account, when, n)
    if want("comment"):
        items += _comment_items(session, ws_id, account, when, n)
    if want("meeting"):
        items += _document_items(session, ws_id, deal_id, account, when, n)
    if want("task"):
        items += _task_items(session, ws_id, deal_id, account, when, n)
    if kinds is not None:
        items = [i for i in items if i.kind in kinds]
    if cursor:
        items = [i for i in items if _key(i) < (cursor[0], cursor[1])]
    items.sort(key=_key, reverse=True)
    page = items[:limit]
    nxt = encode_cursor(page[-1]) if len(items) > limit else None
    return page, nxt
