"""Schemas of the theme endpoints (M2b section 5)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ThemeRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    k: int | None = Field(default=None, ge=2, le=30)
    speakers: Literal["customer", "all"] = "customer"
    use_ai: bool = True


class ExcerptOut(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    account_id: uuid.UUID
    account_name: str
    meeting_date: date | None
    speaker: str | None
    text: str


class ThemeOut(BaseModel):
    id: uuid.UUID
    seq: int
    label: str
    description: str | None
    kind: str
    named_by: str
    origin: Literal["known", "discovered"]
    top_terms: list[str]
    n_chunks: int
    n_documents: int
    n_accounts: int
    excerpts: list[ExcerptOut]
    status: Literal["exploratory"] = "exploratory"


class DroppedOut(BaseModel):
    top_terms: list[str]
    n_chunks: int


class ThemeRunOut(BaseModel):
    run_id: uuid.UUID
    created_at: datetime
    k: int
    n_chunks_used: int
    n_unassigned: int
    dropped_themes: list[DroppedOut]
    known_themes: list[str] = []
    themes: list[ThemeOut]
