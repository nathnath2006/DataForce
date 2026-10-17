"""LLM / embedding usage log: one `llm_call` row per provider call."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import LlmCall
from app.db.session import session_scope
from app.domain.schemas import LLMCallRecord
from app.services.textclean import scrub_text

log = logging.getLogger(__name__)

_ERROR_MAX_CHARS = 500


class DbUsageRecorder:
    """`UsageRecorder` that writes each call in its own short transaction, so a usage row
    survives even when the company-level transaction that triggered the call rolls back.

    Recording is best-effort: a failure here (DB down, run_id unknown) is logged and swallowed,
    it must never abort an extraction that already succeeded."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        workspace_id: uuid.UUID,
        run_id: uuid.UUID | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._workspace_id = workspace_id
        self._run_id = run_id

    def record(self, call: LLMCallRecord) -> None:
        row = LlmCall(
            workspace_id=self._workspace_id,
            run_id=self._run_id,
            provider=call.provider,
            model=call.model,
            purpose=call.purpose,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            latency_ms=call.latency_ms,
            success=call.success,
            # Provider error messages can echo request fragments: keep only a short head.
            error=scrub_text(call.error)[:_ERROR_MAX_CHARS] if call.error else None,
        )
        try:
            with session_scope(self._session_factory) as session:
                session.add(row)
        except Exception:
            log.warning(
                "could not record LLM usage for %s/%s", call.provider, call.model, exc_info=True
            )


def usage_summary(
    session: Session, ws_id: uuid.UUID, run_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    """Calls, failures and tokens grouped by provider / model / purpose."""
    stmt = (
        select(
            LlmCall.provider,
            LlmCall.model,
            LlmCall.purpose,
            func.count().label("calls"),
            func.count().filter(LlmCall.success.is_(False)).label("failures"),
            func.coalesce(func.sum(LlmCall.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(LlmCall.output_tokens), 0).label("output_tokens"),
        )
        .where(LlmCall.workspace_id == ws_id)
        .group_by(LlmCall.provider, LlmCall.model, LlmCall.purpose)
        .order_by(LlmCall.provider, LlmCall.model, LlmCall.purpose)
    )
    if run_id is not None:
        stmt = stmt.where(LlmCall.run_id == run_id)
    return [dict(row._mapping) for row in session.execute(stmt)]
