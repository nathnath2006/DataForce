"""Settings -> AI model and the assistant (M2a section 6). Owned by agent H."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import AppSettings, CurrentViewer, CurrentWorkspace, Db
from app.api.schemas_ai import (
    DATA_NOTICE,
    AiSettingsIn,
    AiSettingsOut,
    AskIn,
    AskOut,
    AskScopeOut,
    Citation,
    MeetingOrgIn,
    QuoteCheck,
)
from app.assistant.ask import run_turn
from app.assistant.context import build_context, validate_scope
from app.assistant.ratelimit import check_and_count
from app.auth.visibility import require_admin
from app.config import Settings
from app.db.models import LlmCredential
from app.domain.ports import ChatMessage, ChatProvider
from app.enrichment.errors import EnrichmentError
from app.llm.errors import LLMError
from app.llm.registry import get_chat_llm
from app.services import llm_settings, org_ai
from app.services.llm_usage import DbUsageRecorder

router = APIRouter(tags=["ai"])

ChatFactory = Callable[..., ChatProvider]


def get_chat_factory() -> ChatFactory:
    """Builds the text provider; tests override this dependency with the fake provider."""
    return get_chat_llm


Factory = Annotated[ChatFactory, Depends(get_chat_factory)]


def _out(cred: LlmCredential | None) -> AiSettingsOut:
    base: dict[str, Any] = {
        "suggested_models": llm_settings.SUGGESTED_MODELS,
        "data_notice": DATA_NOTICE,
    }
    if cred is None:
        return AiSettingsOut(configured=False, **base)
    return AiSettingsOut(
        configured=True,
        provider=cred.provider,
        model=cred.model,
        updated_at=cred.updated_at,
        last_test_at=cred.last_test_at,
        last_test_ok=cred.last_test_ok,
        last_error=cred.last_error,
        allow_meeting_org=cred.allow_meeting_org,
        **base,
    )


def _provider(
    db: Session, ws_id: uuid.UUID, cred: LlmCredential, settings: Settings, factory: ChatFactory
) -> tuple[ChatProvider, str]:
    """(provider, plain key). The usage recorder writes in its own short transaction."""
    key = llm_settings.open_key(cred, settings)
    recorder = DbUsageRecorder(
        sessionmaker(bind=db.get_bind(), join_transaction_mode="create_savepoint"),
        workspace_id=ws_id,
    )
    try:
        provider = factory(
            cred.provider, api_key=key, model=cred.model, settings=settings, usage=recorder
        )
    except LLMError as exc:
        raise EnrichmentError(llm_settings.sanitize_error(str(exc), key)) from None
    return provider, key


async def _call(provider: ChatProvider, coro: Any, key: str) -> Any:
    try:
        return await coro
    except LLMError as exc:
        raise EnrichmentError(llm_settings.sanitize_error(str(exc), key)) from None
    finally:
        aclose = getattr(provider, "aclose", None)
        if aclose is not None:
            with contextlib.suppress(Exception):  # closing is best effort
                await aclose()


@router.get("/w/{ws}/ai", response_model=AiSettingsOut)
def get_ai(db: Db, ws: CurrentWorkspace, viewer: CurrentViewer) -> AiSettingsOut:
    require_admin(viewer)
    return _out(llm_settings.get_credential(db, ws.id))


@router.put("/w/{ws}/ai", response_model=AiSettingsOut)
def put_ai(
    body: AiSettingsIn, db: Db, ws: CurrentWorkspace, settings: AppSettings, viewer: CurrentViewer
) -> AiSettingsOut:
    require_admin(viewer)
    cred = llm_settings.save_settings(
        db,
        ws.id,
        provider=body.provider,
        model=body.model,
        api_key=body.api_key,
        settings=settings,
    )
    db.commit()
    return _out(cred)


@router.put("/w/{ws}/ai/meeting-org", response_model=AiSettingsOut)
def put_meeting_org(
    body: MeetingOrgIn, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> AiSettingsOut:
    """The opt-in switch of the AI pass over meeting sentences (409 without AI settings)."""
    require_admin(viewer)
    cred = org_ai.set_allow(db, ws.id, body.enabled)
    db.commit()
    return _out(cred)


@router.delete("/w/{ws}/ai", status_code=204)
def delete_ai(db: Db, ws: CurrentWorkspace, viewer: CurrentViewer) -> Response:
    require_admin(viewer)
    llm_settings.delete_settings(db, ws.id)
    db.commit()
    return Response(status_code=204)


@router.post("/w/{ws}/ai/test", response_model=AiSettingsOut)
def test_ai(
    db: Db, ws: CurrentWorkspace, settings: AppSettings, factory: Factory, viewer: CurrentViewer
) -> AiSettingsOut:
    require_admin(viewer)
    cred = llm_settings.require_credential(db, ws.id)
    check_and_count(ws.id, settings.assistant_max_asks_per_hour)
    provider, key = _provider(db, ws.id, cred, settings, factory)
    try:
        asyncio.run(
            _call(
                provider,
                provider.generate_text(
                    system="You are a connection test. Reply with OK.",
                    messages=[ChatMessage(role="user", content="Reply with OK")],
                    purpose="connection_test",
                    max_output_tokens=5,
                ),
                key,
            )
        )
        llm_settings.record_test(db, cred, True, None)
    except EnrichmentError as exc:
        llm_settings.record_test(db, cred, False, str(exc))
    db.commit()
    return _out(cred)


@router.get("/w/{ws}/assistant/scope", response_model=AskScopeOut)
def ask_scope(
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    kind: Literal["account", "company", "deal"],
    id: uuid.UUID,
) -> AskScopeOut:
    """Name of the scope and of its company, for the notice shown before asking."""
    name, company = validate_scope(db, ws.id, kind, id, viewer)
    return AskScopeOut(kind=kind, name=name, company_name=company)


@router.post("/w/{ws}/assistant/ask", response_model=AskOut)
def ask(
    body: AskIn,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    factory: Factory,
    viewer: CurrentViewer,
) -> AskOut:
    validate_scope(db, ws.id, body.scope.kind, body.scope.id, viewer)  # 404 before the quota counts
    check_and_count(ws.id, settings.assistant_max_asks_per_hour)
    cred = llm_settings.require_credential(db, ws.id)
    ctx, _title = build_context(
        db,
        ws.id,
        body.scope.kind,
        body.scope.id,
        max_chars=settings.assistant_max_context_chars,
        viewer=viewer,
    )
    provider, key = _provider(db, ws.id, cred, settings, factory)
    history = [ChatMessage(role=t.role, content=t.content) for t in body.history]
    result, checked = asyncio.run(
        _call(
            provider,
            run_turn(
                provider,
                ctx,
                body.question,
                history,
                max_output_tokens=settings.assistant_max_output_tokens,
            ),
            key,
        )
    )
    db.commit()  # nothing of ours to save (no question, no answer)
    return AskOut(
        answer=checked.answer,
        citations=[Citation(**c) for c in checked.citations],  # type: ignore[arg-type]
        quotes=[QuoteCheck(**q) for q in checked.quotes],  # type: ignore[arg-type]
        unverified_numbers=checked.unverified_numbers,
        numbers_from_notes=checked.numbers_from_notes,
        provider=provider.name,
        model=provider.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        context_chars=len(ctx.render()),
        truncated=ctx.truncated,
    )
