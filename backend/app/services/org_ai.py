"""Opt-in AI pass over meeting sentences (docs/ORG-AI-CONTRACT.md): budgets, failure memory,
the per-transcript cache and the calls. Everything the model returns is verified by
`app.orgchart.meeting_ai` before it is kept; this module never writes proposals."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Document, MeetingOrgAiCache
from app.llm.errors import LLMError
from app.orgchart import meeting_ai
from app.orgchart.meetings import ChunkRec, ContactRef
from app.services import llm_settings
from app.services._budget import FAILURE_TTL_S, Budget  # noqa: F401 (re-exported)
from app.services.llm_usage import DbUsageRecorder

# In-memory, process-wide, per workspace (like the title pass): a daily call cap on top of the
# per-run cap, and a short memory of transcripts whose calls failed.
_BUDGET = Budget()
_FAILED = _BUDGET.failed


def reset_limits() -> None:
    _BUDGET.reset()


def _recently_failed(key: tuple[uuid.UUID, uuid.UUID, str]) -> bool:
    return _BUDGET.recently_failed(key)


def _remember_failure(key: tuple[uuid.UUID, uuid.UUID, str]) -> None:
    _BUDGET.remember_failure(key)


# --- settings ---------------------------------------------------------------------------------
def set_allow(session: Session, ws_id: uuid.UUID, enabled: bool) -> Any:
    """The switch lives on the AI settings row (409 when there is none)."""
    cred = llm_settings.require_credential(session, ws_id)
    cred.allow_meeting_org = enabled
    session.flush()
    return cred


def enabled(session: Session, ws_id: uuid.UUID) -> bool:
    cred = llm_settings.get_credential(session, ws_id)
    return bool(cred is not None and cred.allow_meeting_org)


# --- cache purges -----------------------------------------------------------------------------
def purge_account_cache(session: Session, ws_id: uuid.UUID, account_id: uuid.UUID) -> None:
    """Drop the cached findings of every transcript of the account (a contact was erased)."""
    session.execute(
        delete(MeetingOrgAiCache)
        .where(
            MeetingOrgAiCache.workspace_id == ws_id,
            MeetingOrgAiCache.document_id.in_(
                select(Document.id).where(
                    Document.workspace_id == ws_id, Document.account_id == account_id
                )
            ),
        )
        .execution_options(synchronize_session=False)
    )


# --- the pass ---------------------------------------------------------------------------------
@dataclass
class AiStats:
    used: bool = True
    calls: int = 0
    capped: int = 0
    failed: int = 0
    dropped: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "used": self.used,
            "calls": self.calls,
            "capped": self.capped,
            "failed": self.failed,
            "dropped": self.dropped,
        }


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AiPass:
    """One pass over one or several accounts, sharing the per-run budget."""

    def __init__(
        self,
        session: Session,
        ws_id: uuid.UUID,
        settings: Settings,
        factory: Callable[..., Any],
    ) -> None:
        cred = llm_settings.require_credential(session, ws_id)
        self.session, self.ws_id, self.settings, self.factory = session, ws_id, settings, factory
        self.provider_name, self.model = cred.provider, cred.model
        self.stats = AiStats()
        self._left = settings.org_ai_max_calls_per_run

    def _take(self) -> bool:
        """Check and spend the per-run and the per-day allowance under one lock."""
        if self._left <= 0 or not _BUDGET.take(self.ws_id, self.settings.org_ai_max_calls_per_day):
            return False
        self._left -= 1
        return True

    def _open(self) -> Any:
        cred = llm_settings.require_credential(self.session, self.ws_id)
        key = llm_settings.open_key(cred, self.settings)
        recorder = DbUsageRecorder(
            sessionmaker(bind=self.session.get_bind(), join_transaction_mode="create_savepoint"),
            workspace_id=self.ws_id,
        )
        return self.factory(
            cred.provider, api_key=key, model=cred.model, settings=self.settings, usage=recorder
        )

    def _evidence(self, ev: dict[str, Any]) -> dict[str, Any]:
        return {**ev, "provider": self.provider_name, "model": self.model}

    def find(
        self,
        docs: dict[uuid.UUID, str],
        chunks: Sequence[ChunkRec],
        contacts: Sequence[ContactRef],
    ) -> list[meeting_ai.Verified]:
        """Verified findings (rules 1-4) for the account's transcripts; cached or asked."""
        turns = meeting_ai.candidate_turns(chunks, contacts, docs)
        by_doc: dict[uuid.UUID, list[meeting_ai.Turn]] = defaultdict(list)
        for t in turns:
            by_doc[t.document_id].append(t)
        known = {c.id for c in contacts}
        out: list[meeting_ai.Verified] = []
        todo: list[tuple[uuid.UUID, str, list[meeting_ai.Turn], str]] = []
        for doc_id, dturns in by_doc.items():
            sha = _sha(docs[doc_id])
            row = self.session.scalar(
                select(MeetingOrgAiCache).where(
                    MeetingOrgAiCache.document_id == doc_id,
                    MeetingOrgAiCache.text_sha256 == sha,
                    MeetingOrgAiCache.provider == self.provider_name,
                    MeetingOrgAiCache.model == self.model,
                )
            )
            if row is not None:
                out += self._decode(row.findings, docs[doc_id], known)
            elif _recently_failed((self.ws_id, doc_id, sha)):
                self.stats.failed += 1
            else:
                todo.append((doc_id, sha, dturns, docs[doc_id]))
        if todo:
            out += asyncio.run(self._ask_all(todo, contacts))
        return out

    def _decode(
        self, rows: list[dict[str, Any]], text: str, known: set[uuid.UUID]
    ) -> list[meeting_ai.Verified]:
        out = []
        for r in rows:
            try:
                cid = uuid.UUID(r["contact_id"])
                mid = uuid.UUID(r["manager_id"]) if r.get("manager_id") else None
                ev = r["evidence"]
                a, b = ev["char_start"], ev["char_end"]
            except (KeyError, ValueError, TypeError):
                continue
            if cid not in known or (mid is not None and mid not in known):
                continue
            if text[a:b] != ev.get("excerpt"):
                continue
            if "manager_excerpt" in ev and (
                text[ev.get("manager_char_start", 0) : ev.get("manager_char_end", 0)]
                != ev["manager_excerpt"]
            ):
                continue
            out.append(meeting_ai.Verified(r["kind"], cid, mid, ev))
        return out

    async def _ask_all(
        self,
        todo: list[tuple[uuid.UUID, str, list[meeting_ai.Turn], str]],
        contacts: Sequence[ContactRef],
    ) -> list[meeting_ai.Verified]:
        try:
            provider = self._open()
        except LLMError:
            self.stats.failed += len(todo)
            return []
        out: list[meeting_ai.Verified] = []
        try:
            for doc_id, sha, dturns, text in todo:
                res = await meeting_ai.run_document(provider, dturns, contacts, self._take, text)
                self.stats.calls += res.calls
                self.stats.capped += res.capped
                self.stats.failed += res.failed
                self.stats.dropped += res.dropped
                out += res.verified
                if res.failed:
                    _remember_failure((self.ws_id, doc_id, sha))
                if res.complete:
                    self._cache(
                        MeetingOrgAiCache(
                            workspace_id=self.ws_id,
                            document_id=doc_id,
                            text_sha256=sha,
                            provider=self.provider_name,
                            model=self.model,
                            findings=[
                                {
                                    "kind": v.kind,
                                    "contact_id": str(v.contact_id),
                                    "manager_id": str(v.manager_id) if v.manager_id else None,
                                    "evidence": v.evidence,
                                }
                                for v in res.verified
                            ],
                        )
                    )
        finally:
            aclose = getattr(provider, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(Exception):
                    await aclose()
        self.session.flush()
        return out

    def _cache(self, row: MeetingOrgAiCache) -> None:
        """Insert in a savepoint: a cache error never aborts the request after calls were spent."""
        try:
            with self.session.begin_nested():
                self.session.add(row)
        except Exception:  # noqa: S110 - the cache is best effort; findings are still returned
            pass

    def stamp(self, v: meeting_ai.Verified) -> dict[str, Any]:
        return self._evidence(v.evidence)
