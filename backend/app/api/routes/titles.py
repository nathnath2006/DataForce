"""Title normalisation endpoints (M2b section 3). Owned by agent T."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import AppSettings, CurrentViewer, CurrentWorkspace, Db
from app.api.schemas_titles import (
    NormalizeIn,
    NormalizeOut,
    PreviewOut,
    ReviewItem,
    TitleClassIn,
)
from app.db.models import Account, Contact
from app.llm.registry import get_chat_llm
from app.services import titles
from app.services._common import require
from app.titles.classify import classify_title

router = APIRouter(tags=["titles"])


def get_title_factory() -> Callable[..., Any]:
    """Builds the AI provider; tests override this dependency with the fake provider."""
    return get_chat_llm


Factory = Annotated[Callable[..., Any], Depends(get_title_factory)]


def _item(contact: Contact, account_name: str) -> ReviewItem:
    return ReviewItem(
        contact_id=contact.id,
        full_name=contact.full_name,
        account_id=contact.account_id,
        account_name=account_name,
        title=contact.title,
        function=contact.title_function or "unknown",
        seniority=contact.title_seniority or "unknown",
        source=contact.title_source or "unknown",
        flag=contact.title_flag,
    )


@router.post("/w/{ws}/titles/normalize", response_model=NormalizeOut)
def normalize(
    body: NormalizeIn,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    factory: Factory,
    viewer: CurrentViewer,
) -> NormalizeOut:
    summary = titles.normalize_workspace(
        db, ws.id, use_ai=body.use_ai, settings=settings, factory=factory, viewer=viewer
    )
    db.commit()
    return NormalizeOut(**summary)


@router.get("/w/{ws}/titles/review", response_model=list[ReviewItem])
def review(
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[ReviewItem]:
    return [_item(c, name) for c, name in titles.review_items(db, ws.id, limit, viewer)]


@router.get("/w/{ws}/titles/preview", response_model=PreviewOut)
def preview(
    ws: CurrentWorkspace,
    title: Annotated[str, Query(max_length=200, pattern=r"^[^\x00-\x1f\x7f]*$")] = "",
) -> PreviewOut:
    cls = classify_title(title)
    return PreviewOut(
        normalized=cls.normalized,
        function=cls.function.value,
        seniority=cls.seniority.value,
        source=cls.source,
        flag=cls.flag,
        matched=cls.matched,
    )


@router.put("/w/{ws}/contacts/{contact_id}/title-class", response_model=ReviewItem)
def put_title_class(
    contact_id: uuid.UUID, body: TitleClassIn, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> ReviewItem:
    contact = titles.set_manual_class(db, ws.id, contact_id, body.function, body.seniority, viewer)
    account = require(db, Account, ws.id, contact.account_id)
    db.commit()
    return _item(contact, account.name)
