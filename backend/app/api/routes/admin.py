"""Admin view: database size, schema status, operational limits, runs, AI usage (read-only)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from alembic.runtime.migration import MigrationContext
from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import CurrentWorkspace, Db
from app.api.schemas_admin import (
    AdminAiUsage,
    AdminLimit,
    AdminOverview,
    AdminRun,
    AdminRuns,
)
from app.config import get_settings
from app.db.models import LlmCall
from app.domain.enums import RunKind, RunStatus
from app.services import schema as schema_service
from app.services.admin import db_size
from app.services.llm_usage import usage_summary
from app.services.runs import list_runs

router = APIRouter(tags=["admin"])

STALE_AFTER = timedelta(hours=1)
_ERROR_SHORT = 200

# Fixed allow-list of (setting, description). Never add a secret, key, URL or password.
_LIMITS: tuple[tuple[str, str], ...] = (
    ("titles_max_llm_calls_per_run", "AI calls for title normalisation, per run"),
    ("titles_max_llm_calls_per_day", "AI calls for title normalisation, per workspace and day"),
    ("org_ai_max_calls_per_run", "AI calls for org-chart proposals, per run"),
    ("org_ai_max_calls_per_day", "AI calls for org-chart proposals, per workspace and day"),
    ("assistant_max_asks_per_hour", "Assistant questions per workspace and hour"),
    ("assistant_max_context_chars", "Assistant: maximum context characters sent to the model"),
    ("assistant_max_output_tokens", "Assistant: maximum answer tokens"),
    ("llm_max_calls_per_run", "AI calls, hard ceiling per run"),
    ("flow_max_concurrent_runs", "Analysis flows that may run at the same time"),
    ("flow_max_rows", "Maximum rows per dataset or block in a flow"),
    ("flow_run_timeout_s", "Flow run timeout (seconds)"),
    ("upload_max_bytes", "Maximum upload size (bytes)"),
    ("transcript_max_bytes", "Transcript: maximum file size (bytes)"),
    ("transcript_max_pages", "Transcript: maximum PDF pages"),
    ("transcript_max_chars", "Transcript: maximum characters"),
    ("db_statement_timeout_ms", "Database statement timeout (ms, 0 = none)"),
    ("db_lock_timeout_ms", "Database lock timeout (ms, 0 = none)"),
    ("data_connection_timeout_s", "External database query timeout (seconds)"),
)


def _limits() -> list[AdminLimit]:
    settings = get_settings()
    return [AdminLimit(name=n, value=getattr(settings, n), description=d) for n, d in _LIMITS]


@router.get("/w/{ws}/admin/overview", response_model=AdminOverview)
def overview(db: Db, ws: CurrentWorkspace) -> AdminOverview:
    # M3b: admin role only (the database section is global, not workspace data)
    settings = get_settings()
    current = MigrationContext.configure(db.connection()).get_current_revision()
    head = schema_service.head_revision()
    return AdminOverview.model_validate(
        {
            "database": db_size(db, settings.db_quota_mb),
            "schema_status": {"current": current, "head": head, "up_to_date": current == head},
            "limits": _limits(),
        }
    )


def _summary(kind: str, params: dict) -> str:
    tool = params.get("tool") if isinstance(params, dict) else None
    if isinstance(tool, str):
        return f"{kind}: {tool}"[:80]
    keys = sorted(params)[:4] if isinstance(params, dict) else []
    return ", ".join(keys)[:80]


@router.get("/w/{ws}/admin/runs", response_model=AdminRuns)
def runs(
    db: Db,
    ws: CurrentWorkspace,
    kind: RunKind | None = None,
    status: RunStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdminRuns:
    now = datetime.now(UTC)
    out = []
    for r in list_runs(db, ws.id, kind=kind, status=status, limit=limit):
        out.append(
            AdminRun(
                id=r.id,
                kind=r.kind,
                status=r.status,
                started_at=r.started_at,
                finished_at=r.finished_at,
                duration_ms=r.duration_ms,
                error=(r.error[:_ERROR_SHORT] if r.error else None),
                summary=_summary(r.kind, r.params),
                stale=r.status == RunStatus.RUNNING.value and now - r.started_at > STALE_AFTER,
            )
        )
    return AdminRuns(runs=out, stale_after_s=int(STALE_AFTER.total_seconds()))


@router.get("/w/{ws}/admin/ai-usage", response_model=AdminAiUsage)
def ai_usage(
    db: Db, ws: CurrentWorkspace, days: Annotated[int, Query(ge=1, le=365)] = 30
) -> AdminAiUsage:
    settings = get_settings()
    now = datetime.now(UTC)
    rows = usage_summary(db, ws.id, since=now - timedelta(days=days))
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    counts = dict(
        db.execute(
            select(LlmCall.purpose, func.count())
            .where(LlmCall.workspace_id == ws.id, LlmCall.created_at >= midnight)
            .group_by(LlmCall.purpose)
        ).all()
    )
    caps = {
        "title_classification": settings.titles_max_llm_calls_per_day,
        "explanation": settings.org_ai_max_calls_per_day,
    }
    today = [
        {"purpose": p, "calls": counts.get(p, 0), "daily_cap": caps.get(p)}
        for p in sorted(set(counts) | set(caps))
    ]
    return AdminAiUsage(
        source="llm_call table (persisted calls, not the in-memory budgets)",
        days=days,
        rows=rows,
        today=today,
    )
