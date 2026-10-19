"""Job-title classification: dictionary, cached AI fallback, manual overrides (M2b section 3)."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import case, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Account, Contact, TitleCache
from app.domain.enums import JobFunction, RunKind, RunStatus, Seniority, TitleSource
from app.services import llm_settings
from app.services._budget import Budget
from app.services._common import require_contact
from app.services.llm_usage import DbUsageRecorder
from app.services.runs import finish_run, start_run
from app.titles.ai import classify_titles
from app.titles.classify import TitleClass, classify_title

FLAG_NO_AI = "unknown title (no AI model configured)"
FLAG_AI_CAPPED = "unknown title (AI call limit reached)"
FLAG_AI_FAILED = "unknown title (AI call failed)"
FLAG_UNKNOWN = "unknown title"


# In-memory AI budget (process-wide, per workspace): a daily call cap on top of the per-run cap
# (SR12-09), and a short negative cache so a title the provider failed on is not retried.
_BUDGET = Budget()


def reset_ai_limits() -> None:
    _BUDGET.reset()


def _daily_remaining(ws_id: uuid.UUID, settings: Settings) -> int:
    return _BUDGET.remaining(ws_id, settings.titles_max_llm_calls_per_day)


def _spend(ws_id: uuid.UUID, n: int) -> None:
    _BUDGET.spend(ws_id, n)


def _recently_failed(ws_id: uuid.UUID, title: str) -> bool:
    return _BUDGET.recently_failed((ws_id, title))


def _remember_failure(ws_id: uuid.UUID, title: str) -> None:
    _BUDGET.remember_failure((ws_id, title))


def _apply(contact: Contact, cls: TitleClass) -> None:
    contact.title_function = cls.function.value
    contact.title_seniority = cls.seniority.value
    contact.title_source = TitleSource.DICTIONARY.value if cls.source == "dictionary" else None
    contact.title_flag = cls.flag


def classify_contact_title(contact: Contact) -> None:
    """Dictionary only. A manual classification is never touched."""
    if contact.title_source == TitleSource.MANUAL.value:
        return
    _apply(contact, classify_title(contact.title))


def _llm_flag(confidence: str) -> str:
    return f"classified by AI (confidence {confidence}): check"


def _open_provider(
    session: Session, ws_id: uuid.UUID, settings: Settings, factory: Callable[..., Any]
) -> Any | None:
    cred = llm_settings.get_credential(session, ws_id)
    if cred is None:
        return None
    key = llm_settings.open_key(cred, settings)
    recorder = DbUsageRecorder(
        sessionmaker(bind=session.get_bind(), join_transaction_mode="create_savepoint"),
        workspace_id=ws_id,
    )
    return factory(cred.provider, api_key=key, model=cred.model, settings=settings, usage=recorder)


async def _run_ai(provider: Any, titles: list[str]) -> list[tuple[str, Any]]:
    try:
        return await classify_titles(provider, titles)
    finally:
        aclose = getattr(provider, "aclose", None)
        if aclose is not None:
            with contextlib.suppress(Exception):
                await aclose()


def normalize_workspace(
    session: Session,
    ws_id: uuid.UUID,
    *,
    use_ai: bool,
    settings: Settings,
    factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Classify every non-manual contact. Returns the summary also stored on the run."""
    if factory is None:
        from app.llm.registry import get_chat_llm

        factory = get_chat_llm
    run = start_run(session, RunKind.TITLE_NORMALIZE, ws_id, {"use_ai": use_ai})
    contacts = list(
        session.scalars(select(Contact).where(Contact.workspace_id == ws_id).order_by(Contact.id))
    )
    todo: list[tuple[Contact, TitleClass]] = []
    for c in contacts:
        if c.title_source == TitleSource.MANUAL.value:
            continue
        todo.append((c, classify_title(c.title)))

    cache = {
        row.normalized_title: row
        for row in session.scalars(select(TitleCache).where(TitleCache.workspace_id == ws_id))
    }
    unresolved = sorted(
        {cls.normalized for _, cls in todo if cls.source == "none" and cls.normalized}
    )
    to_ask = [t for t in unresolved if t not in cache]
    failed: set[str] = {t for t in to_ask if _recently_failed(ws_id, t)}
    to_ask = [t for t in to_ask if t not in failed]

    provider = _open_provider(session, ws_id, settings, factory) if use_ai else None
    ai_configured = llm_settings.get_credential(session, ws_id) is not None
    llm_calls = 0
    capped: set[str] = set()
    if provider is not None and to_ask:
        allowance = min(settings.titles_max_llm_calls_per_run, _daily_remaining(ws_id, settings))
        batch = to_ask[:allowance]
        capped = set(to_ask[len(batch) :])
        if batch:
            results = asyncio.run(_run_ai(provider, batch))
            llm_calls = len(batch)
            _spend(ws_id, llm_calls)
            for title, answer in results:
                if answer is None:
                    failed.add(title)
                    _remember_failure(ws_id, title)
                    continue
                row = TitleCache(
                    workspace_id=ws_id,
                    normalized_title=title,
                    function=answer.function.value,
                    seniority=answer.seniority.value,
                    confidence=answer.confidence,
                    provider=str(getattr(provider, "name", "unknown"))[:32],
                    model=str(getattr(provider, "model", "unknown"))[:64],
                )
                session.add(row)
                cache[title] = row
            session.flush()

    by_source = {"dictionary": 0, "llm": 0, "manual": 0, "unknown": 0}
    for c, cls in todo:
        if cls.source == "dictionary":
            _apply(c, cls)
        else:
            hit = cache.get(cls.normalized)
            if hit is not None:
                c.title_function, c.title_seniority = hit.function, hit.seniority
                c.title_source = TitleSource.LLM.value
                c.title_flag = _llm_flag(hit.confidence)
            else:
                _apply(c, cls)
                if cls.normalized:
                    if cls.normalized in failed:
                        c.title_flag = FLAG_AI_FAILED
                    elif cls.normalized in capped:
                        c.title_flag = FLAG_AI_CAPPED
                    elif use_ai and not ai_configured:
                        c.title_flag = FLAG_NO_AI
                    else:
                        c.title_flag = FLAG_UNKNOWN
    for c in contacts:
        by_source[c.title_source or "unknown"] += 1
    n_flagged = sum(1 for c in contacts if c.title_flag)
    session.flush()
    summary = {
        "run_id": str(run.id),
        "n_contacts": len(contacts),
        "by_source": by_source,
        "n_flagged": n_flagged,
        "llm_calls": llm_calls,
        "ai_configured": ai_configured,
    }
    finish_run(session, run, RunStatus.SUCCEEDED, summary)
    return summary


def review_items(session: Session, ws_id: uuid.UUID, limit: int) -> list[tuple[Contact, str]]:
    """(contact, account name): flagged or unknown first."""
    needs_look = case(
        (Contact.title_flag.is_not(None), 0), (Contact.title_function == "unknown", 0), else_=1
    )
    stmt = (
        select(Contact, Account.name)
        .join(Account, Account.id == Contact.account_id)
        .where(Contact.workspace_id == ws_id)
        .order_by(needs_look, Contact.full_name, Contact.id)
        .limit(limit)
    )
    return [(c, name) for c, name in session.execute(stmt)]


def set_manual_class(
    session: Session,
    ws_id: uuid.UUID,
    contact_id: uuid.UUID,
    function: JobFunction,
    seniority: Seniority,
) -> Contact:
    contact = require_contact(session, ws_id, contact_id)
    contact.title_function = function.value
    contact.title_seniority = seniority.value
    contact.title_source = TitleSource.MANUAL.value
    contact.title_flag = None
    session.flush()
    return contact
