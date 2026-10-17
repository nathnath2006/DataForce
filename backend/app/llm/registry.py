"""Pick the LLM / embedding provider from settings.

Provider modules (and their SDKs) are imported lazily so `import app.llm.registry` stays cheap and
works without any SDK key. A missing key raises `LLMConfigError` naming the env var to set.
"""

from __future__ import annotations

import logging

from app.config import Settings
from app.domain.ports import EmbeddingProvider, LLMProvider, UsageRecorder
from app.llm.errors import LLMConfigError

log = logging.getLogger(__name__)


def get_llm(settings: Settings, usage: UsageRecorder | None = None) -> LLMProvider:
    provider = settings.llm_provider
    if provider == "fake":
        from app.llm.fake import FakeLLM

        log.warning("using the FAKE llm: outputs are synthetic")
        return FakeLLM(usage=usage)
    if provider == "gemini":
        from app.llm.gemini import GeminiLLM

        return GeminiLLM(settings, usage)
    if provider == "anthropic":
        from app.llm.anthropic_provider import AnthropicLLM

        return AnthropicLLM(settings, usage)
    raise LLMConfigError(f"Unknown LLM_PROVIDER {provider!r} (expected gemini, anthropic or fake)")


def get_embedder(settings: Settings, usage: UsageRecorder | None = None) -> EmbeddingProvider:
    provider = settings.embedding_provider
    if provider == "fake":
        from app.llm.fake import FakeEmbedder

        log.warning("using the FAKE embedder: vectors are synthetic bag-of-words hashes")
        return FakeEmbedder(dim=settings.embedding_dim, usage=usage)
    if provider == "gemini":
        from app.llm.gemini import GeminiEmbedder

        return GeminiEmbedder(settings, usage)
    raise LLMConfigError(
        f"Unknown EMBEDDING_PROVIDER {provider!r} (expected gemini or fake; Anthropic has no "
        "embeddings API)"
    )
