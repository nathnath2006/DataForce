"""Ports (interfaces) between modules. Every external dependency (LLM, embeddings, TamTam) sits
behind one of these, with a fake implementation, so the tool runs and is tested without them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from app.domain.schemas import EnrichmentRequest, EnrichmentResult, LLMCallRecord

T = TypeVar("T", bound=BaseModel)


class UsageRecorder(Protocol):
    """Sink for LLM usage (persisted to llm_call by the services layer)."""

    def record(self, call: LLMCallRecord) -> None: ...


@runtime_checkable
class LLMProvider(Protocol):
    """'Prompt in, structured object out'. Same call for Gemini, Anthropic, OpenAI/Azure.
    The LLM never calculates: it names, classifies and explains facts computed in code."""

    name: str
    model: str

    async def generate_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        purpose: Literal[
            "title_classification",
            "theme_naming",
            "explanation",
            "deal_summary",
            "action_items",
        ],
        max_output_tokens: int = 4096,
    ) -> T: ...


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class TextResult:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class ChatProvider(Protocol):
    """'Conversation in, text out' (M2a assistant). Implemented by the Gemini, Anthropic and fake
    providers. The text is checked after the call: numbers not present in the context and
    quotes not found in the source are flagged (app/assistant)."""

    name: str
    model: str

    async def generate_text(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        purpose: Literal["assistant", "connection_test"],
        max_output_tokens: int = 800,
    ) -> TextResult: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    name: str
    model: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return L2-normalized vectors of length `dim`, one per input text, same order."""
        ...


@runtime_checkable
class EnrichmentProvider(Protocol):
    """People contact enrichment (TamTam connector, M3). Paid lookups only on explicit user
    action: implementations must refuse when `allow_paid` is not True and the lookup costs
    credits."""

    name: str

    async def enrich_contact(
        self, request: EnrichmentRequest, *, allow_paid: bool
    ) -> EnrichmentResult: ...
