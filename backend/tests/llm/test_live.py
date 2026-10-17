"""Live provider checks. Deselected by default (`-m live` to run) and skipped without keys.

GEMINI_API_KEY=... .venv/bin/pytest tests/llm/test_live.py -m live
ANTHROPIC_API_KEY=... .venv/bin/pytest tests/llm/test_live.py -m live
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from app.llm.anthropic_provider import AnthropicLLM
from app.llm.gemini import GeminiEmbedder, GeminiLLM
from tests.llm.helpers import RecordingUsage, TitleLabel, make_settings

pytestmark = pytest.mark.live

# Read at import time: the autouse fixture in conftest.py clears these variables per test.
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
needs_gemini = pytest.mark.skipif(not GEMINI_KEY, reason="GEMINI_API_KEY not set")
needs_anthropic = pytest.mark.skipif(not ANTHROPIC_KEY, reason="ANTHROPIC_API_KEY not set")

SYSTEM = "Classify the job title. Reply with the JSON schema only."


def _settings(**kw):
    return make_settings(gemini_api_key=GEMINI_KEY, anthropic_api_key=ANTHROPIC_KEY, **kw)


@needs_gemini
async def test_gemini_returns_a_valid_object():
    usage = RecordingUsage()
    llm = GeminiLLM(_settings(), usage)
    out = await llm.generate_structured(
        system=SYSTEM, user="Title: VP of Sales", schema=TitleLabel, purpose="title_classification"
    )
    assert out.title and usage.records and usage.records[0].input_tokens


@needs_gemini
async def test_gemini_embeddings_are_normalized_768d():
    emb = GeminiEmbedder(_settings())
    vectors = await emb.embed(["CRM platform for banks", "artisan bakery"])
    assert [len(v) for v in vectors] == [768, 768]
    assert all(np.linalg.norm(v) == pytest.approx(1.0, abs=1e-6) for v in vectors)


@needs_anthropic
async def test_anthropic_returns_a_valid_object():
    usage = RecordingUsage()
    llm = AnthropicLLM(_settings(), usage)
    out = await llm.generate_structured(
        system=SYSTEM, user="Title: VP of Sales", schema=TitleLabel, purpose="title_classification"
    )
    assert out.title and usage.records and usage.records[0].output_tokens
