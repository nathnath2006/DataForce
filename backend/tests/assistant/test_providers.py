"""generate_text on the real providers with stubbed SDK clients (no network)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from anthropic.types import Message, TextBlock, Usage
from google.genai import types

from app.domain.ports import ChatMessage
from app.llm.anthropic_provider import THINKING_HEADROOM, AnthropicLLM
from app.llm.errors import LLMError
from app.llm.fake import FakeLLM
from app.llm.gemini import GeminiLLM
from app.llm.registry import get_chat_llm
from tests.llm.helpers import RecordingUsage, make_settings

MSGS = [ChatMessage(role="user", content="hi"), ChatMessage(role="assistant", content="yo")]


async def test_anthropic_generate_text():
    msg = Message(
        id="m",
        content=[TextBlock(type="text", text=" Hello [F1] ", citations=None)],
        model="x",
        role="assistant",
        stop_reason="end_turn",
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=11, output_tokens=3),
    )
    create = AsyncMock(return_value=msg)
    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    usage = RecordingUsage()
    llm = AnthropicLLM(make_settings(), usage, client=client, model="claude-haiku-5-5")
    res = await llm.generate_text(
        system="sys", messages=MSGS, purpose="assistant", max_output_tokens=100
    )
    assert (res.text, res.input_tokens, res.output_tokens) == ("Hello [F1]", 11, 3)
    kw = create.call_args.kwargs
    assert kw["model"] == "claude-haiku-5-5"
    assert kw["max_tokens"] == 100 + THINKING_HEADROOM
    assert kw["messages"][1] == {"role": "assistant", "content": "yo"}
    assert usage.records[0].purpose == "assistant" and usage.records[0].success


async def test_gemini_generate_text():
    response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(content=types.Content(role="model", parts=[types.Part(text="OK")]))
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=5, candidates_token_count=1
        ),
    )
    generate = AsyncMock(return_value=response)
    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    usage = RecordingUsage()
    llm = GeminiLLM(make_settings(), usage, client=client, model="gemini-2.5-flash")
    res = await llm.generate_text(
        system="sys", messages=MSGS, purpose="connection_test", max_output_tokens=5
    )
    assert res.text == "OK" and res.input_tokens == 5 and res.output_tokens == 1
    kw = generate.call_args.kwargs
    assert [c.role for c in kw["contents"]] == ["user", "model"]
    assert kw["config"].max_output_tokens == 5
    assert usage.records[0].purpose == "connection_test"


async def test_failure_is_labelled_without_the_message():
    class Boom(Exception):
        status_code = 401

    create = AsyncMock(side_effect=Boom("bad key sk-SECRETSECRET123"))
    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    llm = AnthropicLLM(make_settings(), RecordingUsage(), client=client)
    with pytest.raises(LLMError) as ei:
        await llm.generate_text(system="s", messages=MSGS, purpose="assistant")
    assert "SECRET" not in str(ei.value) and "401" in str(ei.value)


async def test_fake_generate_text_and_registry():
    fake = FakeLLM(usage=RecordingUsage())
    assert (
        await fake.generate_text(system="", messages=MSGS, purpose="connection_test")
    ).text == "OK"
    fake.register_text(lambda system, messages: "custom")
    assert (
        await fake.generate_text(system="", messages=MSGS, purpose="assistant")
    ).text == "custom"
    s = make_settings()
    assert get_chat_llm(
        "anthropic", api_key="k" * 30, model="claude-haiku-5-5", settings=s
    ).model == ("claude-haiku-5-5")
    assert get_chat_llm("gemini", api_key="k" * 30, model="gemini-2.5-pro", settings=s).model == (
        "gemini-2.5-pro"
    )
