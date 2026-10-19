"""Shared "prompt in, validated pydantic object out" loop for the real providers.

Each provider only implements `_complete` (one raw API call returning JSON text); this base adds
the concurrency limit, timeout, usage records, schema validation and the single retry on invalid
output, so Gemini and Anthropic behave identically.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.domain.ports import ChatMessage, TextResult, UsageRecorder
from app.llm.errors import LLMError
from app.llm.usage import CallTimer, describe_exception, llm_slot

T = TypeVar("T", bound=BaseModel)

MAX_ATTEMPTS = 2  # first try + one retry on invalid output (spec 3.4)
# Finish reasons for which a second, identical request is not worth a second bill: the model was
# stopped by a safety system or ran out of output budget (SR2-13).
NO_RETRY_FINISH_PREFIXES = (
    "SAFETY", "MAX_TOKENS", "PROHIBITED", "BLOCKLIST", "SPII", "RECITATION", "blocked:", "refusal",
    "max_tokens",
)  # fmt: skip


@dataclass(frozen=True)
class RawCompletion:
    text: str | None
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None  # a provider enum label, never prompt/response content


def strip_json_fences(text: str) -> str:
    """Structured-output modes return bare JSON, but be tolerant of a ```json fence."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t.strip()


def validation_summary(exc: ValidationError) -> str:
    """Field paths + error types only: pydantic's default message echoes the offending input."""
    items = [
        f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['type']}"
        for err in exc.errors(include_input=False, include_url=False)[:8]
    ]
    return "; ".join(items)[:300]


def parse_structured[M: BaseModel](schema: type[M], text: str | None) -> tuple[M | None, str]:
    """Validate raw model output. Returns (object, "") or (None, short problem summary)."""
    if text is None or not text.strip():
        return None, "empty response"
    try:
        return schema.model_validate_json(strip_json_fences(text)), ""
    except ValidationError as exc:
        return None, validation_summary(exc)


def retry_suffix(problem: str) -> str:
    return (
        "\n\nYour previous reply was rejected because it did not match the required JSON schema "
        f"({problem}). Reply again with ONLY one JSON object that conforms exactly to the schema."
    )


class StructuredLLM(ABC):
    """Base for providers implementing `LLMProvider.generate_structured`."""

    name: str
    model: str

    def __init__(self, settings: Settings, usage: UsageRecorder | None) -> None:
        self._settings = settings
        self._usage = usage

    @abstractmethod
    async def _complete(
        self, *, system: str, user: str, schema: type[T], max_output_tokens: int
    ) -> RawCompletion:
        """One raw API call. Raise LLMError for non-retryable failures (refusal, truncation)."""

    async def _complete_text(
        self, *, system: str, messages: list[ChatMessage], max_output_tokens: int
    ) -> RawCompletion:
        """One raw conversation call (assistant). Implemented by the real providers."""
        raise LLMError(f"{self.name}: text generation is not supported")

    async def generate_text(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        purpose: Literal["assistant", "connection_test"],
        max_output_tokens: int = 800,
    ) -> TextResult:
        """`ChatProvider.generate_text`: conversation in, text out. One attempt, no retry."""
        timer = CallTimer(self._usage, provider=self.name, model=self.model, purpose=purpose)
        timeout_s = self._settings.llm_timeout_s
        failure: str | None = None
        raw: RawCompletion | None = None
        try:
            async with llm_slot(self._settings.llm_max_concurrency):
                async with asyncio.timeout(timeout_s):
                    raw = await self._complete_text(
                        system=system, messages=messages, max_output_tokens=max_output_tokens
                    )
        except LLMError as exc:
            timer.failure(str(exc))
            raise
        except TimeoutError:
            failure = f"{self.name}: no response within {timeout_s:.0f}s"
        except Exception as exc:  # label only: see generate_structured (SR2-15)
            failure = f"{self.name}: request failed ({describe_exception(exc)})"
        if failure is not None or raw is None:
            failure = failure or f"{self.name}: no response"
            timer.failure(failure)
            raise LLMError(failure)
        if raw.text is None or not raw.text.strip():
            msg = f"{self.name}: empty response (finish_reason={raw.finish_reason})"
            timer.failure(msg, input_tokens=raw.input_tokens, output_tokens=raw.output_tokens)
            raise LLMError(msg)
        timer.success(input_tokens=raw.input_tokens, output_tokens=raw.output_tokens)
        return TextResult(
            text=raw.text.strip(),
            input_tokens=raw.input_tokens,
            output_tokens=raw.output_tokens,
        )

    async def _guarded_complete(
        self, *, system: str, user: str, schema: type[T], max_output_tokens: int
    ) -> RawCompletion:
        timeout_s = self._settings.llm_timeout_s
        async with llm_slot(self._settings.llm_max_concurrency):
            try:
                async with asyncio.timeout(timeout_s):
                    return await self._complete(
                        system=system,
                        user=user,
                        schema=schema,
                        max_output_tokens=max_output_tokens,
                    )
            except TimeoutError:
                pass  # raised below, outside the handler, so nothing is chained to it
        raise LLMError(f"{self.name}: no response within {timeout_s:.0f}s")

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
    ) -> T:
        problem = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            prompt = user if attempt == 1 else user + retry_suffix(problem)
            timer = CallTimer(self._usage, provider=self.name, model=self.model, purpose=purpose)
            failure: str | None = None
            try:
                raw = await self._guarded_complete(
                    system=system,
                    user=prompt,
                    schema=schema,
                    max_output_tokens=max_output_tokens,
                )
            except LLMError as exc:
                timer.failure(str(exc))
                raise
            except Exception as exc:  # SDK errors: keep only a prompt-free label
                failure = f"{self.name}: request failed ({describe_exception(exc)})"
            if failure is not None:
                # Raised outside the handler on purpose (SR2-15): the SDK exception carries the
                # provider's raw response body (which can echo the prompt or a header) and its
                # request (with the key). Chaining it would put both in any traceback or error
                # report; only the class name / HTTP code survive, in the message.
                timer.failure(failure)
                raise LLMError(failure)

            parsed, problem = parse_structured(schema, raw.text)
            if parsed is not None:
                timer.success(input_tokens=raw.input_tokens, output_tokens=raw.output_tokens)
                return parsed
            timer.failure(
                f"invalid structured output ({problem}; finish_reason={raw.finish_reason})",
                input_tokens=raw.input_tokens,
                output_tokens=raw.output_tokens,
            )
            if raw.finish_reason and raw.finish_reason.startswith(NO_RETRY_FINISH_PREFIXES):
                raise LLMError(f"{self.name}: no usable output ({raw.finish_reason}); not retried")
        raise LLMError(
            f"{self.name}: output did not match the {schema.__name__} schema after "
            f"{MAX_ATTEMPTS} attempts ({problem})"
        )
