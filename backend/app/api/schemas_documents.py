"""Schemas of the transcript endpoints (M2b section 5)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel


class SpeakerOut(BaseModel):
    name: str | None
    contact_id: uuid.UUID | None
    user_id: uuid.UUID | None


class DocumentOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    account_name: str
    deal_id: uuid.UUID | None
    title: str
    meeting_date: date | None
    file_name: str | None
    n_chars: int
    n_chunks: int
    language: str | None
    speakers: list[SpeakerOut]
    theme_labels: list[str]
    created_at: datetime


class ChunkOut(BaseModel):
    id: uuid.UUID
    seq: int
    speaker: str | None
    contact_id: uuid.UUID | None
    user_id: uuid.UUID | None
    char_start: int
    char_end: int


class ChunkTheme(BaseModel):
    chunk_id: uuid.UUID
    theme_id: uuid.UUID
    label: str


class DocumentDetail(DocumentOut):
    text: str
    chunks: list[ChunkOut]
    chunk_themes: list[ChunkTheme]
