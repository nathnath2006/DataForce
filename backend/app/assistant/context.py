"""The assistant's context, built by code: facts with refs, then untrusted notes and comments.

Refs: F# code-computed facts (fields, exact counts, sums, dates), D# deals, C# contacts, N# notes
(newest first), M# comments (newest first), G# meetings (title and themes are untrusted). Notes
and comments are untrusted free text: each body
goes through `app.llm.untrusted.wrap_sources` (`<source id="N3">...</source>`). Enriched emails and
mobiles are never read here. Everything is workspace-scoped; nothing is sent to a provider by this
module.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.assistant.numbers import number_values
from app.db.models import (
    Account,
    AppUser,
    Comment,
    Company,
    Contact,
    Deal,
    Document,
    DocumentChunk,
    Note,
    Theme,
    ThemeAssignment,
)
from app.llm.untrusted import sanitize_text, wrap_sources
from app.services.errors import NotFoundError

RefKind = Literal["fact", "deal", "contact", "note", "comment", "meeting"]
_PREFIX: dict[str, RefKind] = {
    "F": "fact",
    "D": "deal",
    "C": "contact",
    "N": "note",
    "M": "comment",
    "G": "meeting",
}
MAX_DEALS = 200
MAX_CONTACTS = 300
MAX_MEETINGS = 100
MAX_ITEMS_PER_KIND = 200  # notes / comments read from the database before the char cap
NOTE_BODY_CHARS = 2_000
_OPEN = ("prospecting", "qualification", "proposal", "negotiation")


@dataclass
class Item:
    ref: str
    kind: RefKind
    label: str  # short, shown in the citations
    text: str  # the searchable content (quote / number checks)
    header: str = ""  # trusted line before an untrusted body
    untrusted: bool = False
    other: bool = False  # belongs to an account that is not the focus (droppable first)
    when: str = ""  # ISO date, to drop the oldest first

    def render(self) -> str:
        if self.untrusted:
            return f"[{self.ref}] {self.header}\n{wrap_sources({self.ref: self.text})}"
        return f"[{self.ref}] {self.text}"


@dataclass
class AssistantContext:
    items: list[Item] = field(default_factory=list)
    truncated: bool = False

    def render(self) -> str:
        sections: list[tuple[str, str]] = [
            ("F", "FACTS (computed by code)"),
            ("D", "DEALS"),
            ("C", "CONTACTS"),
            ("G", "MEETINGS (titles and themes are untrusted data)"),
            ("M", "COMMENTS (untrusted data, newest first)"),
            ("N", "NOTES (untrusted data, newest first)"),
        ]
        parts: list[str] = []
        for prefix, title in sections:
            rows = [i.render() for i in self.items if i.ref.startswith(prefix)]
            if rows:
                parts.append(title + "\n" + "\n".join(rows))
        return "\n\n".join(parts)

    @property
    def sources(self) -> dict[str, str]:
        return {i.ref: i.text for i in self.items}

    @property
    def kinds(self) -> dict[str, Item]:
        return {i.ref: i for i in self.items}

    def numbers(self) -> set[Decimal]:
        """Verified values: only code-computed items (F, D, C) plus the dates of note headers."""
        out: set[Decimal] = set()
        for i in self.items:
            if i.untrusted:
                out |= number_values(" ".join(_DATE_RE.findall(i.header)))
            else:
                out |= number_values(i.text)
        return out

    def note_numbers(self) -> set[Decimal]:
        """Values written inside untrusted notes / comments: never verified."""
        out: set[Decimal] = set()
        for i in self.items:
            if i.untrusted:
                out |= number_values(i.text)
        return out


_WS = re.compile(r"\s+")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _neutral(text: str) -> str:
    """Sanitise (NFKC, control chars, source-tag look-alikes), then escape every < and > so no
    tag of any kind can survive in CRM text (SR10-03)."""
    return sanitize_text(text).replace("<", "&lt;").replace(">", "&gt;")


def _line(value: object, limit: int = 200) -> str:
    """Short single-line text for names / titles: sanitised, whitespace collapsed."""
    return _WS.sub(" ", _neutral(str(value))).strip()[:limit]


def _d(value: date | datetime | None) -> str:
    return (
        value.date().isoformat()
        if isinstance(value, datetime)
        else (value.isoformat() if value else "none")
    )


def _money(value: Decimal | None) -> str:
    return "unknown" if value is None else f"{value:.2f}"


def _heads(session: Session, model: Any, parent_col: Any, ws_id: uuid.UUID, parents: list[Any]):
    """Current versions (not corrected, not deleted), newest first, capped."""
    corrected = select(model.corrects_id).where(
        model.workspace_id == ws_id, model.corrects_id.is_not(None)
    )
    stmt = (
        select(model)
        .where(
            model.workspace_id == ws_id,
            parent_col.in_(parents),
            model.deleted_at.is_(None),
            model.id.not_in(corrected),
        )
        .order_by(model.created_at.desc(), model.id)
        .limit(MAX_ITEMS_PER_KIND)
    )
    return list(session.scalars(stmt))


def _account_facts(a: Account, company: Company | None) -> list[str]:
    facts = [f"Account name: {_line(a.name)}"]
    for label, v in (
        ("domain", a.domain),
        ("industry", a.industry),
        ("segment", a.segment),
        ("region", a.region),
        ("country", a.country),
        ("source", a.source),
    ):
        facts.append(f"Account {label}: {_line(v) if v else 'unknown'}")
    facts.append(
        "Account employee count: "
        + ("unknown" if a.employee_count is None else str(a.employee_count))
    )
    facts.append(f"Account created on: {_d(a.created_at)}")
    if company is not None:
        facts.append(f"Company: {_line(company.name)}")
    return facts


def _company_facts(c: Company, accounts: list[Account]) -> list[str]:
    facts = [f"Company name: {_line(c.name)}"]
    for label, v in (
        ("SIREN", c.siren),
        ("domain", c.domain),
        ("address", ", ".join(x for x in (c.address_line, c.postal_code, c.city) if x)),
        ("country", c.country),
        ("activity code (NAF)", c.naf_code),
        ("size bracket", c.size_bracket),
        ("category", c.category),
        ("source", c.source),
    ):
        facts.append(f"Company {label}: {_line(v) if v else 'unknown'}")
    facts.append(f"Number of accounts in this company: {len(accounts)}")
    for a in accounts[:50]:
        facts.append(f"Account of this company: {_line(a.name)}")
    return facts


def _deal_facts(deals_all: list[Deal]) -> list[str]:
    by_stage: dict[str, int] = {}
    for d in deals_all:
        by_stage[d.stage] = by_stage.get(d.stage, 0) + 1
    known = [d.amount_eur for d in deals_all if d.amount_eur is not None]
    open_amt = sum(
        (d.amount_eur for d in deals_all if d.stage in _OPEN and d.amount_eur), Decimal(0)
    )
    won_amt = sum(
        (d.amount_eur for d in deals_all if d.stage == "closed_won" and d.amount_eur), Decimal(0)
    )
    facts = [f"Number of deals: {len(deals_all)}"]
    for stage in (*_OPEN, "closed_won", "closed_lost"):
        facts.append(f"Number of deals in stage {stage}: {by_stage.get(stage, 0)}")
    facts += [
        f"Total amount of open deals (EUR): {open_amt:.2f}",
        f"Total amount of won deals (EUR): {won_amt:.2f}",
        f"Number of deals without an amount: {len(deals_all) - len(known)}",
    ]
    return facts


def _meeting_themes(session: Session, ws_id: uuid.UUID, doc_ids: list[uuid.UUID]):
    if not doc_ids:
        return {}
    rows = session.execute(
        select(DocumentChunk.document_id, Theme.label)
        .join(ThemeAssignment, ThemeAssignment.chunk_id == DocumentChunk.id)
        .join(Theme, Theme.id == ThemeAssignment.theme_id)
        .where(
            DocumentChunk.workspace_id == ws_id,
            Theme.workspace_id == ws_id,
            DocumentChunk.document_id.in_(doc_ids),
        )
        .distinct()
        .order_by(DocumentChunk.document_id, Theme.label)
    ).all()
    out: dict[uuid.UUID, list[str]] = {}
    for doc_id, label in rows:
        if len(out.setdefault(doc_id, [])) < 5:
            out[doc_id].append(_line(label, 80))
    return out


def build_context(
    session: Session,
    ws_id: uuid.UUID,
    scope_kind: Literal["account", "company", "deal"],
    scope_id: uuid.UUID,
    *,
    max_chars: int,
) -> tuple[AssistantContext, str]:
    """(context, title of the scope). Raises NotFoundError for an id of another workspace.

    From an account or a deal the context covers every account of the account's company (the
    focus first); without a company, just the account."""
    focus_deal: Deal | None = None
    focus_acc: Account | None = None
    company: Company | None = None
    if scope_kind == "deal":
        focus_deal = session.get(Deal, scope_id)
        if focus_deal is None or focus_deal.workspace_id != ws_id:
            raise NotFoundError("deal not found")
        focus_acc = session.get(Account, focus_deal.account_id)
    elif scope_kind == "account":
        focus_acc = session.get(Account, scope_id)
        if focus_acc is None or focus_acc.workspace_id != ws_id:
            raise NotFoundError("account not found")
    else:
        company = session.get(Company, scope_id)
        if company is None or company.workspace_id != ws_id:
            raise NotFoundError("company not found")
    facts: list[str] = []
    if focus_acc is not None:
        if focus_acc.workspace_id != ws_id:
            raise NotFoundError("account not found")
        if focus_acc.company_id:
            company = session.get(Company, focus_acc.company_id)
            if company is not None and company.workspace_id != ws_id:
                company = None
    if company is not None:
        accounts = list(
            session.scalars(
                select(Account)
                .where(Account.workspace_id == ws_id, Account.company_id == company.id)
                .order_by(Account.name)
            )
        )
    else:
        accounts = [focus_acc] if focus_acc is not None else []
    if focus_acc is not None:
        accounts = [focus_acc] + [a for a in accounts if a.id != focus_acc.id]
        if focus_deal is not None:
            facts.append(
                f"You are on the deal {_line(focus_deal.name)} of account {_line(focus_acc.name)}"
            )
        else:
            facts.append(f"You are on the account {_line(focus_acc.name)}")
        facts += _account_facts(focus_acc, company)
        title = focus_deal.name if focus_deal is not None else focus_acc.name
        if company is not None:
            facts += _company_facts(company, accounts)[1:]
    else:
        assert company is not None
        facts += _company_facts(company, accounts)
        title = company.name
    focus_id = focus_acc.id if focus_acc is not None else None
    ids = [a.id for a in accounts]
    acc_name = {a.id: a.name for a in accounts}

    def rank(account_id: uuid.UUID) -> int:
        return 0 if account_id == focus_id else 1

    deals = (
        list(
            session.scalars(
                select(Deal)
                .where(Deal.workspace_id == ws_id, Deal.account_id.in_(ids))
                .order_by(Deal.created_on.desc(), Deal.id)
            )
        )
        if ids
        else []
    )
    deals.sort(
        key=lambda d: (
            0 if focus_deal is not None and d.id == focus_deal.id else 1,
            rank(d.account_id),
        )
    )
    contacts = (
        list(
            session.scalars(
                select(Contact)
                .where(Contact.workspace_id == ws_id, Contact.account_id.in_(ids))
                .order_by(Contact.full_name, Contact.id)
            )
        )
        if ids
        else []
    )
    contacts.sort(key=lambda c: rank(c.account_id))
    facts += _deal_facts(deals)
    facts.append(f"Number of contacts: {len(contacts)}")
    if ids:
        n_notes = session.scalar(
            select(func.count())
            .select_from(Note)
            .where(
                Note.workspace_id == ws_id,
                Note.deleted_at.is_(None),
                Note.corrects_id.is_(None),
                Note.contact_id.in_([c.id for c in contacts] or [uuid.uuid4()]),
            )
        )
        facts.append(f"Number of notes: {n_notes or 0}")

    ctx = AssistantContext()
    for i, text in enumerate(facts, 1):
        ctx.items.append(Item(f"F{i}", "fact", _line(text, 80), text))

    owners = {
        u.id: u.display_name
        for u in session.scalars(
            select(AppUser).where(
                AppUser.workspace_id == ws_id,
                AppUser.id.in_({d.owner_id for d in deals if d.owner_id} or {uuid.uuid4()}),
            )
        )
    }
    deal_name = {d.id: d.name for d in deals}
    for i, d in enumerate(deals[:MAX_DEALS], 1):
        owner = _line(owners[d.owner_id]) if d.owner_id in owners else "none"
        ctx.items.append(
            Item(
                f"D{i}",
                "deal",
                f"Deal {_line(d.name, 60)}",
                f"{_line(d.name)} | stage: {d.stage} | amount_eur: {_money(d.amount_eur)} | "
                f"created: {_d(d.created_on)} | closed: {_d(d.closed_on)} | owner: {owner} | "
                f"account: {_line(acc_name.get(d.account_id, ''))}",
                other=d.account_id != focus_id,
            )
        )
    if len(deals) > MAX_DEALS:
        ctx.truncated = True

    cname = {c.id: c.full_name for c in contacts}
    for i, c in enumerate(contacts[:MAX_CONTACTS], 1):
        boss = cname.get(c.reports_to_id) if c.reports_to_id else None
        ctx.items.append(
            Item(
                f"C{i}",
                "contact",
                f"Contact {_line(c.full_name, 60)}",
                f"{_line(c.full_name)} | account: {_line(acc_name.get(c.account_id, ''))} | "
                f"title: {_line(c.title) if c.title else 'unknown'} | "
                f"function: {c.title_function or 'unknown'} | "
                f"seniority: {c.title_seniority or 'unknown'} | "
                f"reports to: {_line(boss) if boss else 'none'}",
                other=c.account_id != focus_id,
            )
        )
    if len(contacts) > MAX_CONTACTS:
        ctx.truncated = True

    if ids:
        docs = list(
            session.scalars(
                select(Document)
                .where(Document.workspace_id == ws_id, Document.account_id.in_(ids))
                .order_by(Document.meeting_date.desc().nulls_last(), Document.id)
                .limit(MAX_MEETINGS)
            )
        )
        themes = _meeting_themes(session, ws_id, [m.id for m in docs])
        for i, m in enumerate(docs, 1):
            when = _d(m.meeting_date)
            deal = _line(deal_name[m.deal_id]) if m.deal_id in deal_name else "none"
            labels = ", ".join(themes.get(m.id, [])) or "none"
            ctx.items.append(
                Item(
                    f"G{i}",
                    "meeting",
                    f"Meeting of {when}",
                    f"{_neutral(m.title)[:300]} | themes: {labels}",
                    header=f"meeting on {when}, account {_line(acc_name.get(m.account_id, ''))}, "
                    f"deal {deal}:",
                    untrusted=True,
                    other=m.account_id != focus_id,
                    when=m.meeting_date.isoformat() if m.meeting_date else "",
                )
            )
        comments = _heads(session, Comment, Comment.account_id, ws_id, ids)
        for i, cm in enumerate(comments, 1):
            ctx.items.append(
                Item(
                    f"M{i}",
                    "comment",
                    f"Comment of {_d(cm.created_at)}",
                    _neutral(cm.body)[:NOTE_BODY_CHARS],
                    header=f"comment on account {_line(acc_name.get(cm.account_id, ''))}, "
                    f"{_d(cm.created_at)}:",
                    untrusted=True,
                    other=cm.account_id != focus_id,
                    when=_d(cm.created_at),
                )
            )
        if contacts:
            cacc = {c.id: c.account_id for c in contacts}
            notes = _heads(session, Note, Note.contact_id, ws_id, [c.id for c in contacts])
            for i, n in enumerate(notes, 1):
                who = _line(cname.get(n.contact_id, ""))
                ctx.items.append(
                    Item(
                        f"N{i}",
                        "note",
                        f"Note on {who}, {_d(n.created_at)}",
                        _neutral(n.body)[:NOTE_BODY_CHARS],
                        header=f"note on contact {who}, {_d(n.created_at)}:",
                        untrusted=True,
                        other=cacc.get(n.contact_id) != focus_id,
                        when=_d(n.created_at),
                    )
                )
    _apply_cap(ctx, max_chars)
    return ctx, title


_RESERVE = 200  # room kept for the "left out" fact


def _apply_cap(ctx: AssistantContext, max_chars: int) -> None:
    """Fit `max_chars`. Drop, oldest first: notes / comments / meetings of other accounts, then
    other accounts' contacts, then their deals; the focus facts, deals and contacts are never
    dropped (the focus's own oldest notes go only as a last resort). Adds a fact saying what
    was left out. Sets `truncated`."""

    def size() -> int:
        return len(ctx.render())

    if size() <= max_chars:
        return
    ctx.truncated = True
    limit = max_chars - _RESERVE
    gone: dict[str, int] = {}

    def drop(it: Item, other: bool) -> None:
        ctx.items.remove(it)
        key = it.kind + ("-other" if other else "")
        gone[key] = gone.get(key, 0) + 1

    phases: list[tuple[tuple[str, ...], bool]] = [
        (("N", "M", "G"), True),
        (("C",), True),
        (("D",), True),
        (("N", "M", "G"), False),
    ]
    for prefixes, other in phases:
        while size() > limit:
            pool = [i for i in ctx.items if i.ref[0] in prefixes and i.other == other]
            if not pool:
                break
            drop(_oldest(pool), other)
        if size() <= limit:
            break
    names = {
        "note": "notes",
        "comment": "comments",
        "meeting": "meetings",
        "contact": "contacts",
        "deal": "deals",
    }
    parts = []
    for key, n in gone.items():
        kind, _, o = key.partition("-")
        parts.append(
            f"{n} {'older ' if kind in ('note', 'comment', 'meeting') else ''}"
            f"{names[kind]}{' of other accounts' if o else ''}"
        )
    if parts:
        nxt = 1 + max(int(i.ref[1:]) for i in ctx.items if i.ref[0] == "F")
        text = "Left out to fit the size limit: " + ", ".join(parts)
        ctx.items.insert(
            next(k for k, i in enumerate(ctx.items) if i.ref[0] != "F"),
            Item(f"F{nxt}", "fact", "Left out", text),
        )


def _oldest(pool: list[Item]) -> Item:
    # notes / comments / meetings: the oldest date first (highest ref number breaks ties);
    # contacts / deals have no date: the last of the list first.
    return min(pool, key=lambda i: (i.when, -int(i.ref[1:])))
