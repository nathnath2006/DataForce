"""Plain helpers for the offline LLM tests (no network, no keys)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from app.config import Settings
from app.domain.schemas import LLMCallRecord

ENV_VARS = (
    "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
    "TAMTAM_MCP_TOKEN",
    "LLM_PROVIDER",
    "EMBEDDING_PROVIDER",
    "ENRICHMENT_PROVIDER",
    "GEMINI_MODEL",
    "ANTHROPIC_MODEL",
    "EMBEDDING_DIM",
    "LLM_TIMEOUT_S",
    "LLM_MAX_CONCURRENCY",
    "GOOGLE_API_KEY",
)


def make_settings(**overrides: object) -> Settings:
    """Settings that ignore backend/.env and the process environment."""
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


class RecordingUsage:
    def __init__(self) -> None:
        self.records: list[LLMCallRecord] = []

    def record(self, call: LLMCallRecord) -> None:
        self.records.append(call)


class Level(StrEnum):
    JUNIOR = "junior"
    SENIOR = "senior"


class Item(BaseModel):
    quote: str
    source_id: str


class TitleLabel(BaseModel):
    """Small local schema standing in for the M2 schemas."""

    title: str
    level: Level
    confidence: float
    items: list[Item] = []


def sample_label(**overrides: object) -> TitleLabel:
    data: dict[str, object] = {"title": "VP Sales", "level": Level.SENIOR, "confidence": 0.9}
    data.update(overrides)
    return TitleLabel(**data)  # type: ignore[arg-type]
