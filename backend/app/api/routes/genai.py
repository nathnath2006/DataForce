"""Opt-in GenAI on a deal or account: preview, cited summary, suggested tasks (M4 phase 2).

Accepting or dismissing a suggested task reuses `POST /tasks/{id}/accept` and
`PATCH /tasks/{id}` (status dismissed) of the activities routes."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter

from app.api.deps import AppSettings, CurrentViewer, CurrentWorkspace, Db
from app.api.routes.ai import Factory
from app.api.schemas_genai import (
    ActionItemsOut,
    AiPreview,
    SuggestedTaskOut,
    SummaryOut,
)
from app.db.models import Task
from app.services import genai

router = APIRouter(tags=["genai"])

Scope = Literal["deals", "accounts"]


def _ids(scope: Scope, rid: uuid.UUID) -> dict[str, uuid.UUID]:
    return {"deal_id": rid} if scope == "deals" else {"account_id": rid}


def _task_out(t: Task) -> SuggestedTaskOut:
    ev = t.evidence or {}
    return SuggestedTaskOut(
        id=t.id,
        title=t.title,
        status=t.status,
        source=t.source,
        quote=str(ev.get("quote", "")),
        quote_found=bool(ev.get("quote_found", True)),
        origin={k: str(v) for k, v in (ev.get("origin") or {}).items()},
        deal_id=t.deal_id,
        account_id=t.account_id,
    )


def _open(
    db: Db, ws: CurrentWorkspace, settings: AppSettings, factory: Factory, viewer: CurrentViewer
) -> genai.GenAi:
    return genai.GenAi(db, ws.id, settings, factory, viewer.user_id)


@router.get("/w/{ws}/{scope}/{rid}/ai/preview", response_model=AiPreview)
def preview(
    scope: Scope,
    rid: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    factory: Factory,
    viewer: CurrentViewer,
) -> AiPreview:
    src = genai.collect(db, ws.id, settings, viewer=viewer, **_ids(scope, rid))
    return AiPreview(**_open(db, ws, settings, factory, viewer).preview(src))


@router.post("/w/{ws}/{scope}/{rid}/ai/summary", response_model=SummaryOut)
def summary(
    scope: Scope,
    rid: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    factory: Factory,
    viewer: CurrentViewer,
) -> SummaryOut:
    ai = _open(db, ws, settings, factory, viewer)
    src = genai.collect(db, ws.id, settings, viewer=viewer, **_ids(scope, rid))
    out = SummaryOut(**ai.summarize(src))
    db.commit()
    return out


@router.post("/w/{ws}/{scope}/{rid}/ai/tasks", response_model=ActionItemsOut)
def suggest_tasks(
    scope: Scope,
    rid: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    factory: Factory,
    viewer: CurrentViewer,
) -> ActionItemsOut:
    ai = _open(db, ws, settings, factory, viewer)
    ids = _ids(scope, rid)
    src = genai.collect(db, ws.id, settings, viewer=viewer, **ids)
    res = ai.extract_tasks(src, deal_id=ids.get("deal_id"), account_id=ids.get("account_id"))
    db.commit()
    return ActionItemsOut(
        provider=ai.provider_name,
        model=ai.model,
        tasks=[_task_out(t) for t in res["tasks"]],
        dropped=res["dropped"],
        duplicates=res["duplicates"],
    )
