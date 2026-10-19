"""Schemas of the opt-in GenAI blocks (summary, suggested tasks)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# --- what the model must return (verified by code before anything is kept) ----------------------
class SummarySentence(BaseModel):
    text: str = Field(max_length=800)
    cites: list[str] = Field(max_length=10)  # ids of the source items, e.g. "N3"


class SummaryAnswer(BaseModel):
    sentences: list[SummarySentence] = Field(max_length=12)


class ActionItem(BaseModel):
    title: str = Field(max_length=1000)
    quote: str = Field(max_length=2000)  # exact words from the item
    item_id: str = Field(max_length=40)


class ActionItemsAnswer(BaseModel):
    items: list[ActionItem] = Field(max_length=30)


# --- API ----------------------------------------------------------------------------------------
class AiPreview(BaseModel):
    n_items: int
    n_chars: int
    truncated: bool
    by_kind: dict[str, int]
    provider: str
    model: str
    calls_today: int
    daily_cap: int


class Citation(BaseModel):
    item_id: str
    kind: str
    at: datetime
    origin_id: str  # timeline item id, e.g. "note:<uuid>"


class SummarySentenceOut(BaseModel):
    text: str
    cites: list[Citation]


class SummaryOut(BaseModel):
    ai: bool = True
    provider: str
    model: str
    sentences: list[SummarySentenceOut]
    dropped: int
    # why sentences were dropped: no_citation, number_not_in_source, too_long
    dropped_reasons: dict[str, int] = {}


class SuggestedTaskOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    source: str
    quote: str
    origin: dict[str, str]
    deal_id: uuid.UUID | None
    account_id: uuid.UUID | None


class ActionItemsOut(BaseModel):
    ai: bool = True
    provider: str
    model: str
    tasks: list[SuggestedTaskOut]
    dropped: int
    duplicates: int
