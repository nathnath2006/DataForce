"""SR2-12 (pinned base URLs), SR2-14 (non-finite vectors), SR2-15 (no exception chaining)."""

from __future__ import annotations

import numpy as np
import pytest

from app.llm.anthropic_provider import ANTHROPIC_BASE_URL, make_anthropic_client
from app.llm.errors import LLMError
from app.llm.fake import FakeEmbedder
from app.llm.gemini import GEMINI_BASE_URL, l2_normalize, make_gemini_client
from tests.llm.helpers import make_settings


def test_anthropic_base_url_ignores_the_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil.example")
    client = make_anthropic_client(make_settings(anthropic_api_key="k"))
    assert str(client.base_url).rstrip("/") == ANTHROPIC_BASE_URL


def test_gemini_base_url_ignores_the_environment(monkeypatch):
    monkeypatch.setenv("GOOGLE_GEMINI_BASE_URL", "https://evil.example")
    client = make_gemini_client(make_settings(gemini_api_key="k"))
    assert client._api_client._http_options.base_url == GEMINI_BASE_URL


@pytest.mark.parametrize("bad", [[0.0, 0.0], [float("nan"), 1.0], [float("inf"), 1.0]])
def test_non_finite_or_zero_vectors_are_rejected(bad):
    with pytest.raises(LLMError):
        l2_normalize(bad)


async def test_fake_embedder_vectors_are_finite_and_unit():
    (v,) = await FakeEmbedder(dim=16).embed(["\u0000 ???"])
    assert np.all(np.isfinite(v)) and np.linalg.norm(v) == pytest.approx(1.0)
