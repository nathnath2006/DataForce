"""HTTP contract of Settings -> AI model and the assistant (M2a section 6)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MODEL_PATTERN = r"^[a-z0-9][a-z0-9.\-]{0,63}$"
DATA_NOTICE = (
    "When you ask a question, the question and the data of the account or company you are "
    "viewing (names, deal figures, notes and comments) are sent to the provider you chose. "
    "Enriched emails and phone numbers are never sent. The question and the answer are not stored."
)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AiSettingsIn(_In):
    provider: Literal["gemini", "anthropic"]
    model: str = Field(pattern=MODEL_PATTERN)
    api_key: str | None = Field(default=None, repr=False)

    @field_validator("api_key")
    @classmethod
    def _key_len(cls, v: str | None) -> str | None:
        # An empty key means "keep the stored one". The shape is checked by the service; the
        # length cap here only bounds the request (the value is never echoed in an error).
        if v is not None and len(v) > 2_000:
            raise ValueError("api_key is too long")
        return v


class AiSettingsOut(BaseModel):
    configured: bool
    provider: str | None = None
    model: str | None = None
    updated_at: datetime | None = None
    last_test_at: datetime | None = None
    last_test_ok: bool | None = None
    last_error: str | None = None
    suggested_models: dict[str, list[str]]
    data_notice: str


class AskScope(_In):
    kind: Literal["account", "company"]
    id: UUID


class AskTurn(_In):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4_000)


class AskIn(_In):
    scope: AskScope
    question: str = Field(min_length=1, max_length=2_000)
    history: list[AskTurn] = Field(default_factory=list, max_length=10)


class Citation(BaseModel):
    ref: str
    kind: Literal["fact", "deal", "contact", "note", "comment"]
    label: str


class QuoteCheck(BaseModel):
    text: str
    ref: str
    verified: bool


class AskOut(BaseModel):
    answer: str
    citations: list[Citation]
    quotes: list[QuoteCheck]
    unverified_numbers: list[str]
    numbers_from_notes: list[str] = []
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    context_chars: int
    truncated: bool
