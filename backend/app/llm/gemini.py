"""Gemini providers (Google AI Studio / Gemini Developer API) on the `google-genai` SDK.

Verified against google-genai 2.31.0 (`client.aio.models.generate_content` / `embed_content`).

Structured output: `response_mime_type="application/json"` plus `response_json_schema` built from
the pydantic model (JSON Schema with `$defs`/`$ref`, so enums and nested lists work). The
alternative `response_schema=<pydantic class>` is available with `schema_mode="pydantic"` if the
API ever rejects the JSON-Schema form. The result is always re-validated with
`schema.model_validate_json` (see `_structured.py`), one retry on invalid output.

Embeddings: `gemini-embedding-001`, task `SEMANTIC_SIMILARITY`, `output_dimensionality=dim`.
Vectors below the model's native 3072 dimensions are NOT unit length, so we L2-normalize.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal, TypeVar

import numpy as np
from google import genai
from google.genai import types
from pydantic import BaseModel

from app.config import Settings
from app.domain.ports import ChatMessage, UsageRecorder
from app.llm._structured import RawCompletion, StructuredLLM
from app.llm.errors import LLMError, require_secret
from app.llm.usage import CallTimer, describe_exception, llm_slot

T = TypeVar("T", bound=BaseModel)

# The official endpoint, passed explicitly: the SDK would otherwise read GOOGLE_GEMINI_BASE_URL
# from the process environment and send the API key wherever it points (SR2-12). There is
# deliberately no setting to override it.
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/"
EMBED_BATCH_SIZE = 100  # API limit for one batch embed request
# Output budget added when the model may "think": thinking tokens count against
# max_output_tokens and would otherwise truncate the JSON.
THINKING_HEADROOM = 4096


def make_gemini_client(settings: Settings, api_key: str | None = None) -> genai.Client:
    """Build the SDK client. The key is read here and nowhere else (an explicit `api_key` is the
    workspace's key from Settings; the SDK sends it in the x-goog-api-key header)."""
    key = api_key or require_secret(
        settings.gemini_api_key, "GEMINI_API_KEY", needed_for="the Gemini LLM / embedding provider"
    )
    return genai.Client(
        api_key=key,
        vertexai=False,  # never let GOOGLE_GENAI_USE_VERTEXAI silently redirect us
        http_options=types.HttpOptions(
            base_url=GEMINI_BASE_URL,
            timeout=int(settings.llm_timeout_s * 1000),  # milliseconds
            retry_options=types.HttpRetryOptions(attempts=3),  # 408/429/5xx with backoff
        ),
    )


def gemini_json_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON Schema reduced to the keywords Gemini's `response_json_schema` supports.

    Drops `title`/`default` (unsupported, only noise) and any sibling of a `$ref` (the API
    rejects them). Field names that happen to be called `title`/`default` are preserved.
    """

    def clean(node: Any) -> Any:
        if isinstance(node, list):
            return [clean(x) for x in node]
        if not isinstance(node, dict):
            return node
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in ("title", "default"):
                continue
            if key in ("properties", "$defs") and isinstance(value, dict):
                out[key] = {name: clean(sub) for name, sub in value.items()}
            else:
                out[key] = clean(value)
        if "$ref" in out:
            out = {k: v for k, v in out.items() if k.startswith("$")}
        return out

    return clean(schema.model_json_schema())


class GeminiLLM(StructuredLLM):
    name = "gemini"

    def __init__(
        self,
        settings: Settings,
        usage: UsageRecorder | None = None,
        *,
        client: genai.Client | None = None,
        schema_mode: Literal["json_schema", "pydantic"] = "json_schema",
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(settings, usage)
        self.model = model or settings.gemini_model
        self._schema_mode = schema_mode
        self._client = (
            client if client is not None else make_gemini_client(settings, api_key=api_key)
        )

    async def aclose(self) -> None:
        await self._client.aio.aclose()

    def _thinking_disabled(self) -> bool:
        # 2.5 Flash / Flash-Lite accept budget 0; 2.5 Pro and 3.x cannot turn thinking off.
        return self.model.startswith("gemini-2.5-flash")

    def build_config(
        self, *, system: str, schema: type[BaseModel], max_output_tokens: int
    ) -> types.GenerateContentConfig:
        thinking_off = self._thinking_disabled()
        kwargs: dict[str, Any] = {
            "system_instruction": system,
            "response_mime_type": "application/json",
            "max_output_tokens": max_output_tokens + (0 if thinking_off else THINKING_HEADROOM),
        }
        if self._schema_mode == "pydantic":
            kwargs["response_schema"] = schema
        else:
            kwargs["response_json_schema"] = gemini_json_schema(schema)
        if thinking_off:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        if not self.model.startswith("gemini-3"):  # Gemini 3 advises keeping the default (1.0)
            kwargs["temperature"] = 0.0
        return types.GenerateContentConfig(**kwargs)

    async def _complete_text(
        self, *, system: str, messages: list[ChatMessage], max_output_tokens: int
    ) -> RawCompletion:
        thinking_off = self._thinking_disabled()
        kwargs: dict[str, Any] = {
            "system_instruction": system,
            "max_output_tokens": max_output_tokens + (0 if thinking_off else THINKING_HEADROOM),
        }
        if thinking_off:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        if not self.model.startswith("gemini-3"):
            kwargs["temperature"] = 0.0
        contents = [
            types.Content(
                role="user" if m.role == "user" else "model",
                parts=[types.Part(text=m.content)],
            )
            for m in messages
        ]
        response = await self._client.aio.models.generate_content(
            model=self.model, contents=contents, config=types.GenerateContentConfig(**kwargs)
        )
        return self._raw(response)

    async def _complete(
        self, *, system: str, user: str, schema: type[T], max_output_tokens: int
    ) -> RawCompletion:
        config = self.build_config(
            system=system, schema=schema, max_output_tokens=max_output_tokens
        )
        response = await self._client.aio.models.generate_content(
            model=self.model, contents=user, config=config
        )
        return self._raw(response)

    @staticmethod
    def _raw(response: Any) -> RawCompletion:
        candidates = response.candidates or []
        text: str | None = None
        finish: str | None = None
        if candidates:
            finish = getattr(candidates[0].finish_reason, "name", None)
            parts = candidates[0].content.parts if candidates[0].content else None
            chunks = [p.text for p in (parts or []) if p.text and not p.thought]
            text = "".join(chunks) if chunks else None
        elif response.prompt_feedback is not None:
            finish = f"blocked:{getattr(response.prompt_feedback.block_reason, 'name', 'unknown')}"
        meta = response.usage_metadata
        out_tokens: int | None = None
        if meta is not None and (
            meta.candidates_token_count is not None or meta.thoughts_token_count is not None
        ):
            out_tokens = (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)
        return RawCompletion(
            text=text,
            input_tokens=meta.prompt_token_count if meta is not None else None,
            output_tokens=out_tokens,
            finish_reason=finish,
        )


def l2_normalize(values: list[float]) -> list[float]:
    arr = np.asarray(values, dtype=np.float64)
    norm = float(np.linalg.norm(arr))
    if not np.isfinite(norm) or norm == 0.0:
        raise LLMError("gemini: embedding has zero or non-finite norm")
    return (arr / norm).tolist()


class GeminiEmbedder:
    name = "gemini"

    def __init__(
        self,
        settings: Settings,
        usage: UsageRecorder | None = None,
        *,
        client: genai.Client | None = None,
    ) -> None:
        self._settings = settings
        self._usage = usage
        self.model = settings.gemini_embedding_model
        self.dim = settings.embedding_dim
        self._client = client if client is not None else make_gemini_client(settings)

    async def aclose(self) -> None:
        await self._client.aio.aclose()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if any(not t.strip() for t in texts):
            raise LLMError("gemini: cannot embed an empty text")
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            vectors.extend(await self._embed_batch(texts[start : start + EMBED_BATCH_SIZE]))
        return vectors

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        timer = CallTimer(self._usage, provider=self.name, model=self.model, purpose="embedding")
        config = types.EmbedContentConfig(
            task_type="SEMANTIC_SIMILARITY", output_dimensionality=self.dim
        )
        failure: str | None = None
        out: list[list[float]] = []
        try:
            async with llm_slot(self._settings.llm_max_concurrency):
                async with asyncio.timeout(self._settings.llm_timeout_s):
                    response = await self._client.aio.models.embed_content(
                        model=self.model, contents=batch, config=config
                    )
            embeddings = response.embeddings or []
            if len(embeddings) != len(batch):
                raise LLMError(f"gemini: expected {len(batch)} embeddings, got {len(embeddings)}")
            for emb in embeddings:
                values = list(emb.values or [])
                if len(values) != self.dim:
                    raise LLMError(
                        f"gemini: embedding has {len(values)} dimensions, expected {self.dim}"
                    )
                out.append(l2_normalize(values))
        except LLMError as exc:
            timer.failure(str(exc))
            raise
        except TimeoutError:
            failure = f"gemini: embedding timed out after {self._settings.llm_timeout_s:.0f}s"
        except Exception as exc:
            failure = f"gemini: embedding request failed ({describe_exception(exc)})"
        if failure is not None:
            # Raised outside the `except` blocks: the SDK exception (its message is the
            # provider's response body, its request carries the key) is neither the __cause__
            # nor the __context__ of ours, so no traceback / error reporter can reach it (SR2-15).
            timer.failure(failure)
            raise LLMError(failure)
        timer.success()  # embed_content reports no token counts on the Developer API
        return out
