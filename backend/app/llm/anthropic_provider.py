"""Anthropic provider: the "swap proof" second `LLMProvider`.

Verified against anthropic 1.15.0 and the claude-api skill (2026-10).

Schema-conformant JSON comes from **structured outputs**: `output_config={"format": {"type":
"json_schema", "schema": ...}}` on `messages.create`, with the schema produced by the SDK's own
`anthropic.transform_schema(<pydantic class>)` (adds `additionalProperties: false`, folds
unsupported constraints into descriptions). Forced tool use is not used: `tool_choice` any/tool
returns a 400 on the current Claude models. The reply is still validated with
`schema.model_validate_json` (one retry on invalid output, see `_structured.py`).

Deliberately NOT sent: `temperature`/`top_p` (400 on the current models), `thinking` (Haiku 5.5
and Sonnet 5.5 reject `disabled`; adaptive thinking is the default and its tokens count against
`max_tokens`, hence `THINKING_HEADROOM`), `effort` (not accepted by Haiku 4.5 / Sonnet 4.5).

There are no embeddings here: Anthropic does not offer an embeddings API, so
`embedding_provider` can only be "gemini" or "fake".
"""

from __future__ import annotations

from typing import TypeVar

import anthropic
from pydantic import BaseModel

from app.config import Settings
from app.domain.ports import UsageRecorder
from app.llm._structured import RawCompletion, StructuredLLM
from app.llm.errors import LLMError, require_secret

T = TypeVar("T", bound=BaseModel)

# Added to the caller's output budget because adaptive thinking (on by default on the 5.x
# models) is billed as output and shares `max_tokens`.
THINKING_HEADROOM = 4096
SDK_MAX_RETRIES = 2  # SDK-level retries for 408/409/429/5xx and connection errors
# The official endpoint, passed explicitly: the SDK would otherwise read ANTHROPIC_BASE_URL from
# the process environment and send the API key wherever it points (SR2-12). No override setting.
ANTHROPIC_BASE_URL = "https://api.anthropic.com"


def make_anthropic_client(settings: Settings) -> anthropic.AsyncAnthropic:
    key = require_secret(
        settings.anthropic_api_key, "ANTHROPIC_API_KEY", needed_for="the Anthropic LLM provider"
    )
    return anthropic.AsyncAnthropic(
        api_key=key,
        base_url=ANTHROPIC_BASE_URL,
        timeout=settings.llm_timeout_s,
        max_retries=SDK_MAX_RETRIES,
    )


class AnthropicLLM(StructuredLLM):
    name = "anthropic"

    def __init__(
        self,
        settings: Settings,
        usage: UsageRecorder | None = None,
        *,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        super().__init__(settings, usage)
        self.model = settings.anthropic_model
        self._client = client if client is not None else make_anthropic_client(settings)

    async def aclose(self) -> None:
        await self._client.close()

    async def _complete(
        self, *, system: str, user: str, schema: type[T], max_output_tokens: int
    ) -> RawCompletion:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=max_output_tokens + THINKING_HEADROOM,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "format": {"type": "json_schema", "schema": anthropic.transform_schema(schema)}
            },
        )
        stop = response.stop_reason
        if stop == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) or "unspecified"
            raise LLMError(f"anthropic: the model declined the request (category: {category})")
        if stop == "max_tokens":
            raise LLMError("anthropic: output was truncated at max_tokens; raise max_output_tokens")
        text = next((b.text for b in response.content if b.type == "text"), None)
        return RawCompletion(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            finish_reason=stop,
        )
