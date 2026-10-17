"""Provider selection from settings, and clear errors for missing keys."""

from __future__ import annotations

import pytest

from app.domain.ports import EmbeddingProvider, LLMProvider
from app.llm.anthropic_provider import AnthropicLLM
from app.llm.errors import LLMConfigError, LLMError
from app.llm.fake import FakeEmbedder, FakeLLM
from app.llm.gemini import GeminiEmbedder, GeminiLLM
from app.llm.registry import get_embedder, get_llm
from tests.llm.helpers import RecordingUsage, make_settings


def test_fake_providers_are_selected_without_any_key():
    s = make_settings(llm_provider="fake", embedding_provider="fake", embedding_dim=128)
    llm, emb = get_llm(s), get_embedder(s)
    assert isinstance(llm, FakeLLM) and isinstance(emb, FakeEmbedder)
    assert emb.dim == 128
    assert isinstance(llm, LLMProvider) and isinstance(emb, EmbeddingProvider)


def test_usage_recorder_is_passed_to_the_provider():
    usage = RecordingUsage()
    s = make_settings(llm_provider="fake", embedding_provider="fake")
    assert get_llm(s, usage)._usage is usage
    assert get_embedder(s, usage)._usage is usage


def test_gemini_is_selected_with_a_key_and_uses_settings_models():
    s = make_settings(
        llm_provider="gemini",
        embedding_provider="gemini",
        gemini_api_key="k",
        gemini_model="gemini-2.5-flash-lite",
        gemini_embedding_model="gemini-embedding-001",
        embedding_dim=768,
    )
    llm, emb = get_llm(s), get_embedder(s)
    assert isinstance(llm, GeminiLLM) and llm.model == "gemini-2.5-flash-lite"
    assert isinstance(emb, GeminiEmbedder) and emb.model == "gemini-embedding-001"
    assert emb.dim == 768
    assert isinstance(llm, LLMProvider) and isinstance(emb, EmbeddingProvider)


def test_anthropic_is_selected_with_a_key():
    s = make_settings(
        llm_provider="anthropic", anthropic_api_key="k", anthropic_model="claude-sonnet-5-5"
    )
    llm = get_llm(s)
    assert isinstance(llm, AnthropicLLM) and llm.model == "claude-sonnet-5-5"
    assert isinstance(llm, LLMProvider)


@pytest.mark.parametrize(
    ("kwargs", "getter", "env_var"),
    [
        ({"llm_provider": "gemini"}, get_llm, "GEMINI_API_KEY"),
        ({"embedding_provider": "gemini"}, get_embedder, "GEMINI_API_KEY"),
        ({"llm_provider": "anthropic"}, get_llm, "ANTHROPIC_API_KEY"),
        ({"llm_provider": "anthropic", "anthropic_api_key": ""}, get_llm, "ANTHROPIC_API_KEY"),
    ],
)
def test_missing_key_raises_a_clear_error_naming_the_variable(kwargs, getter, env_var):
    with pytest.raises(LLMConfigError) as exc:
        getter(make_settings(**kwargs))
    assert env_var in str(exc.value)
    assert isinstance(exc.value, LLMError)


def test_default_settings_without_keys_fail_loudly_not_silently_fake():
    with pytest.raises(LLMConfigError, match="GEMINI_API_KEY"):
        get_llm(make_settings())  # default llm_provider is gemini


def test_the_key_never_appears_in_errors_or_reprs():
    s = make_settings(llm_provider="gemini", gemini_api_key="sk-very-secret")
    assert "sk-very-secret" not in repr(s) and "sk-very-secret" not in str(s)
    llm = get_llm(s)
    assert "sk-very-secret" not in repr(llm.__dict__.get("_settings"))


def test_importing_the_registry_does_not_import_any_sdk():
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "import sys; import app.llm.registry as r; import app.enrichment.registry as e; "
        "from app.config import Settings; "
        "r.get_llm(Settings(_env_file=None, llm_provider='fake')); "
        "bad = [m for m in ('google.genai', 'anthropic', 'mcp') if m in sys.modules]; "
        "assert not bad, bad"
    )
    backend = Path(__file__).resolve().parents[2]
    subprocess.run([sys.executable, "-c", code], cwd=backend, check=True)
