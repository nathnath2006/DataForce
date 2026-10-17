"""Theme analysis endpoints (docs/M2B-CONTRACT.md section 5)."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import AppSettings, CurrentWorkspace, Db
from app.api.errors import error_response
from app.api.routes.ai import ChatFactory, get_chat_factory
from app.api.schemas_themes import DroppedOut, ExcerptOut, ThemeOut, ThemeRunIn, ThemeRunOut
from app.llm.errors import LLMError
from app.services import llm_settings
from app.services import themes as svc
from app.services.llm_usage import DbUsageRecorder
from app.themes.naming import Named, ai_name

router = APIRouter(tags=["themes"])
Factory = Annotated[ChatFactory, Depends(get_chat_factory)]


def _make_namer(db: Session, ws_id, settings, factory: ChatFactory) -> svc.Namer | None:
    cred = llm_settings.get_credential(db, ws_id)
    if cred is None:
        return None
    key = llm_settings.open_key(cred, settings)
    recorder = DbUsageRecorder(
        sessionmaker(bind=db.get_bind(), join_transaction_mode="create_savepoint"),
        workspace_id=ws_id,
    )
    try:
        provider = factory(
            cred.provider, api_key=key, model=cred.model, settings=settings, usage=recorder
        )
    except LLMError:
        return None

    def namer(inputs: list[svc.NamingInput]) -> list[Named | None]:
        async def one(inp: svc.NamingInput) -> Named | None:
            try:
                return await ai_name(provider, inp.top_terms, inp.excerpts)  # type: ignore[arg-type]
            except Exception:  # one theme failing falls back to keywords
                return None

        async def all_() -> list[Named | None]:
            try:
                return [await one(i) for i in inputs]
            finally:
                aclose = getattr(provider, "aclose", None)
                if aclose is not None:
                    with contextlib.suppress(Exception):
                        await aclose()

        return asyncio.run(all_())

    return namer


def _run_out(db: Db, ws_id, run, k, n_used, n_unassigned, dropped, known=()) -> ThemeRunOut:
    views = svc.themes_of_run(db, ws_id, run.id)
    return ThemeRunOut(
        run_id=run.id,
        created_at=run.started_at,
        k=k,
        n_chunks_used=n_used,
        n_unassigned=n_unassigned,
        dropped_themes=[
            DroppedOut(top_terms=d["top_terms"], n_chunks=d["n_chunks"]) for d in dropped
        ],
        known_themes=list(known),
        themes=[
            ThemeOut(
                id=v.theme.id,
                seq=v.theme.seq,
                label=v.theme.label,
                description=v.theme.description,
                kind=v.theme.kind,
                named_by=v.theme.named_by,
                origin="known" if v.theme.named_by == "lexicon" else "discovered",
                top_terms=list(v.theme.top_terms),
                n_chunks=v.n_chunks,
                n_documents=v.n_documents,
                n_accounts=v.n_accounts,
                excerpts=[ExcerptOut(**e.__dict__) for e in v.excerpts],
            )
            for v in views
        ],
    )


@router.post("/w/{ws}/themes/run", response_model=ThemeRunOut)
def run_themes(
    body: ThemeRunIn, db: Db, ws: CurrentWorkspace, settings: AppSettings, factory: Factory
) -> ThemeRunOut:
    k = body.k or settings.themes_default_k
    namer = _make_namer(db, ws.id, settings, factory) if body.use_ai else None
    res = svc.run_themes(db, ws.id, k=k, speakers=body.speakers, namer=namer)
    db.commit()
    dropped = [{"top_terms": d.top_terms, "n_chunks": d.n_chunks} for d in res.dropped]
    return _run_out(
        db, ws.id, res.run, k, res.n_chunks_used, res.n_unassigned, dropped, res.known_themes
    )


@router.get("/w/{ws}/themes/latest", response_model=ThemeRunOut)
def latest(db: Db, ws: CurrentWorkspace):
    run = svc.latest_run(db, ws.id)
    if run is None:
        return error_response(404, "not_found", "no theme analysis yet")
    result = run.result or {}
    return _run_out(
        db,
        ws.id,
        run,
        int((run.params or {}).get("k", 0)),
        int(result.get("n_chunks_used", 0)),
        int(result.get("n_unassigned", 0)),
        result.get("dropped", []),
        result.get("known_themes", []),
    )
