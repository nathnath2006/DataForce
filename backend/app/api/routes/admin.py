"""Admin view: database size, schema status, operational limits, runs, AI usage (read-only)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from alembic.runtime.migration import MigrationContext
from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import func, select

from app.api.deps import AppSettings, CurrentViewer, CurrentWorkspace, Db, SuperAdmin
from app.api.schemas_admin import (
    AdminAiUsage,
    AdminLimit,
    AdminOverview,
    AdminRun,
    AdminRuns,
    EditableLimit,
    LimitUpdate,
    ModelPriceIn,
    ModelPriceOut,
    UsageReport,
    UsageReportAll,
)
from app.auth.demo import NotDemo
from app.auth.visibility import require_admin
from app.config import get_settings
from app.db.models import LlmCall, ModelPrice, SettingOverride, UserAccount
from app.domain.enums import RunKind, RunStatus
from app.services import limits as limits_service
from app.services import schema as schema_service
from app.services import usage as usage_service
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


def _limits(settings) -> list[AdminLimit]:
    return [AdminLimit(name=n, value=getattr(settings, n), description=d) for n, d in _LIMITS]


@router.get("/w/{ws}/admin/overview", response_model=AdminOverview)
def overview(db: Db, ws: CurrentWorkspace, viewer: CurrentViewer) -> AdminOverview:
    require_admin(viewer)
    # M3b: admin role only (the database section is global, not workspace data)
    settings = limits_service.effective_settings(db, get_settings(), ws.id)
    current = MigrationContext.configure(db.connection()).get_current_revision()
    head = schema_service.head_revision()
    return AdminOverview.model_validate(
        {
            "database": db_size(db, settings.db_quota_mb),
            "schema_status": {"current": current, "head": head, "up_to_date": current == head},
            "limits": _limits(settings),
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
    viewer: CurrentViewer,
    kind: RunKind | None = None,
    status: RunStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdminRuns:
    require_admin(viewer)
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
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> AdminAiUsage:
    require_admin(viewer)
    settings = limits_service.effective_settings(db, get_settings(), ws.id)
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
        "deal_summary": settings.genai_max_calls_per_day,
        "action_items": settings.genai_max_calls_per_day,
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


# --- Admin-editable limits --------------------------------------------------------------------
def _editable(db, settings, ws_id, show_names: bool = True) -> list[EditableLimit]:
    """Every allow-listed limit as seen from `ws_id` (None = the global view)."""
    rows = {
        (o.key, o.workspace_id): o
        for o in db.scalars(
            select(SettingOverride).where(
                SettingOverride.workspace_id.is_(None)
                if ws_id is None
                else (SettingOverride.workspace_id == ws_id)
                | SettingOverride.workspace_id.is_(None)
            )
        )
    }
    ids = {o.updated_by for o in rows.values() if o.updated_by}
    names = {
        u.id: u.display_name for u in db.scalars(select(UserAccount).where(UserAccount.id.in_(ids)))
    }
    out = []
    for d in limits_service.LIMITS:
        value, source = limits_service.resolve(db, settings, d.key, ws_id)
        row = (
            rows.get((d.key, ws_id if source == "workspace" else None))
            if source != "default"
            else None
        )
        out.append(
            EditableLimit(
                key=d.key,
                value=value,
                default=limits_service.default_of(settings, d.key),
                source=source,  # type: ignore[arg-type]
                min=d.minimum,
                max=d.maximum,
                unit=d.unit,
                description=d.description,
                group=d.group,
                kind=d.kind,  # type: ignore[arg-type]
                global_value=limits_service.effective(db, settings, d.key, None)
                if ws_id is not None
                else None,
                updated_at=row.updated_at if row else None,
                updated_by=(
                    names.get(row.updated_by) if show_names and row and row.updated_by else None
                ),
                workspace_editable=d.key not in limits_service.GLOBAL_ONLY,
            )
        )
    return out


def _one(db, settings, ws_id, key: str) -> EditableLimit:
    return next(x for x in _editable(db, settings, ws_id, show_names=ws_id is None) if x.key == key)


@router.get("/admin/limits", response_model=list[EditableLimit])
def global_limits(db: Db, user: SuperAdmin, settings: AppSettings) -> list[EditableLimit]:
    return _editable(db, settings, None)


@router.put("/admin/limits/{key}", response_model=EditableLimit, dependencies=[NotDemo])
def put_global_limit(
    key: str, body: LimitUpdate, db: Db, user: SuperAdmin, settings: AppSettings
) -> EditableLimit:
    limits_service.set_override(db, key, None, body.value, user.id)
    db.commit()
    limits_service.invalidate()
    return _one(db, settings, None, key)


@router.get("/w/{ws}/admin/limits", response_model=list[EditableLimit])
def workspace_limits(
    db: Db, ws: CurrentWorkspace, viewer: CurrentViewer, settings: AppSettings
) -> list[EditableLimit]:
    require_admin(viewer)
    return _editable(db, settings, ws.id, show_names=False)


@router.put("/w/{ws}/admin/limits/{key}", response_model=EditableLimit, dependencies=[NotDemo])
def put_workspace_limit(
    key: str,
    body: LimitUpdate,
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    settings: AppSettings,
) -> EditableLimit:
    """A workspace value may only be lower than (or equal to) the global one."""
    require_admin(viewer)
    if key in limits_service.GLOBAL_ONLY:
        raise HTTPException(status_code=400, detail="this limit is global only")
    limits_service.set_override(db, key, ws.id, body.value, viewer.user_id, settings)
    db.commit()
    limits_service.invalidate()
    return _one(db, settings, ws.id, key)


# --- Usage per user, model, day and purpose ------------------------------------------------------
@router.get("/w/{ws}/admin/usage", response_model=UsageReport)
def workspace_usage(
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict:
    require_admin(viewer)
    return usage_service.summary(db, ws.id, days)


@router.get("/admin/usage", response_model=UsageReportAll)
def global_usage(db: Db, user: SuperAdmin, days: Annotated[int, Query(ge=1, le=365)] = 30) -> dict:
    return usage_service.summary(db, None, days)


def _price_out(p: ModelPrice) -> ModelPriceOut:
    return ModelPriceOut(
        id=p.id,
        provider=p.provider,
        model=p.model,
        input_per_mtok_eur=float(p.input_per_mtok_eur),
        output_per_mtok_eur=float(p.output_per_mtok_eur),
        updated_at=p.updated_at,
    )


@router.get("/admin/model-prices", response_model=list[ModelPriceOut])
def model_prices(db: Db, user: SuperAdmin) -> list[ModelPriceOut]:
    return [_price_out(p) for p in usage_service.prices(db).values()]


@router.put("/admin/model-prices", response_model=ModelPriceOut, dependencies=[NotDemo])
def put_model_price(body: ModelPriceIn, db: Db, user: SuperAdmin) -> ModelPriceOut:
    row = usage_service.set_price(
        db,
        body.provider,
        body.model,
        body.input_per_mtok_eur,
        body.output_per_mtok_eur,
        user.id,
    )
    db.commit()
    return _price_out(row)


@router.delete("/admin/model-prices/{price_id}", status_code=204, dependencies=[NotDemo])
def delete_model_price(price_id: uuid.UUID, db: Db, user: SuperAdmin) -> Response:
    if not usage_service.delete_price(db, price_id):
        raise HTTPException(status_code=404, detail="no such price")
    db.commit()
    return Response(status_code=204)
