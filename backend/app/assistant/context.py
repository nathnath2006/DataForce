"""The assistant's context, built by code: facts with refs, then untrusted notes and comments.

Refs: F# code-computed facts (fields, exact counts, sums, dates), D# deals, C# contacts, N# notes
(newest first), M# comments (newest first). Notes and comments are untrusted free text: each body
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
from app.db.models import Account, AppUser, Comment, Company, Contact, Deal, Note
from app.llm.untrusted import sanitize_text, wrap_sources
from app.services.errors import NotFoundError

RefKind = Literal["fact", "deal", "contact", "note", "comment"]
_PREFIX: dict[str, RefKind] = {
    "F": "fact",
    "D": "deal",
    "C": "contact",
    "N": "note",
    "M": "comment",
}
MAX_DEALS = 60
MAX_CONTACTS = 100
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
        out: set[Decimal] = set()
        for i in self.items:
            out |= number_values(i.text)
            out |= number_values(i.header)
        return out


_WS = re.compile(r"\s+")


def _line(value: object, limit: int = 200) -> str:
    """Short single-line text for names / titles: sanitised, whitespace collapsed."""
    return _WS.sub(" ", sanitize_text(str(value))).strip()[:limit]


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


def build_context(
    session: Session,
    ws_id: uuid.UUID,
    scope_kind: Literal["account", "company"],
    scope_id: uuid.UUID,
    *,
    max_chars: int,
) -> tuple[AssistantContext, str]:
    """(context, title of the scope). Raises NotFoundError for an id of another workspace."""
    accounts: list[Account]
    facts: list[str]
    if scope_kind == "account":
        account = session.get(Account, scope_id)
        if account is None or account.workspace_id != ws_id:
            raise NotFoundError("account not found")
        accounts = [account]
        company = session.get(Company, account.company_id) if account.company_id else None
        if company is not None and company.workspace_id != ws_id:
            company = None
        facts = _account_facts(account, company)
        title = account.name
    else:
        company = session.get(Company, scope_id)
        if company is None or company.workspace_id != ws_id:
            raise NotFoundError("company not found")
        accounts = list(
            session.scalars(
                select(Account)
                .where(Account.workspace_id == ws_id, Account.company_id == company.id)
                .order_by(Account.name)
            )
        )
        facts = _company_facts(company, accounts)
        title = company.name
    ids = [a.id for a in accounts]
    acc_name = {a.id: a.name for a in accounts}

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
    multi = scope_kind == "company"
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
    for i, d in enumerate(deals[:MAX_DEALS], 1):
        owner = _line(owners[d.owner_id]) if d.owner_id in owners else "none"
        where = f" | account: {_line(acc_name.get(d.account_id, ''))}" if multi else ""
        ctx.items.append(
            Item(
                f"D{i}",
                "deal",
                f"Deal {_line(d.name, 60)}",
                f"{_line(d.name)} | stage: {d.stage} | amount_eur: {_money(d.amount_eur)} | "
                f"created: {_d(d.created_on)} | closed: {_d(d.closed_on)} | owner: {owner}{where}",
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
                f"{_line(c.full_name)} | title: {_line(c.title) if c.title else 'unknown'} | "
                f"reports to: {_line(boss) if boss else 'none'}",
            )
        )
    if len(contacts) > MAX_CONTACTS:
        ctx.truncated = True

    if ids:
        comments = _heads(session, Comment, Comment.account_id, ws_id, ids)
        for i, cm in enumerate(comments, 1):
            ctx.items.append(
                Item(
                    f"M{i}",
                    "comment",
                    f"Comment of {_d(cm.created_at)}",
                    sanitize_text(cm.body)[:NOTE_BODY_CHARS],
                    header=f"comment on account {_line(acc_name.get(cm.account_id, ''))}, "
                    f"{_d(cm.created_at)}:",
                    untrusted=True,
                )
            )
        if contacts:
            notes = _heads(session, Note, Note.contact_id, ws_id, [c.id for c in contacts])
            for i, n in enumerate(notes, 1):
                who = _line(cname.get(n.contact_id, ""))
                ctx.items.append(
                    Item(
                        f"N{i}",
                        "note",
                        f"Note on {who}, {_d(n.created_at)}",
                        sanitize_text(n.body)[:NOTE_BODY_CHARS],
                        header=f"note on contact {who}, {_d(n.created_at)}:",
                        untrusted=True,
                    )
                )
    _apply_cap(ctx, max_chars)
    return ctx, title


def _apply_cap(ctx: AssistantContext, max_chars: int) -> None:
    """Drop the oldest notes / comments (the tail of N and M) until the context fits; if the
    facts alone are too long, drop deals then contacts from the end. Sets `truncated`."""

    def size() -> int:
        return len(ctx.render())

    if size() <= max_chars:
        return
    ctx.truncated = True
    for prefixes in (("N", "M"), ("D",), ("C",)):
        while size() > max_chars:
            # oldest first: highest number, alternating between notes and comments by date
            pool = [i for i in ctx.items if i.ref[0] in prefixes]
            if not pool:
                break
            ctx.items.remove(pool[-1] if len(prefixes) == 1 else _oldest(pool))
        if size() <= max_chars:
            return


def _oldest(pool: list[Item]) -> Item:
    # label ends with the ISO date for notes ("..., 2026-03-04") and comments ("Comment of ...")
    return min(pool, key=lambda i: (i.label[-10:], -int(i.ref[1:])))
