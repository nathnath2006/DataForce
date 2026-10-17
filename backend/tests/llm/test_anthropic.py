"""AnthropicLLM with the AsyncAnthropic client mocked (real SDK response types, no network)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import pytest
from anthropic.types import Message, TextBlock, ThinkingBlock, Usage

from app.llm.anthropic_provider import THINKING_HEADROOM, AnthropicLLM, make_anthropic_client
from app.llm.errors import LLMConfigError, LLMError
from tests.llm.helpers import RecordingUsage, TitleLabel, make_settings, sample_label

SECRET_PROMPT = "TOP-SECRET-PROMPT-MARKER-67890"
VALID = sample_label().model_dump_json()


def message(text, *, stop="end_turn", inp=20, out=8, blocks=None):
    content = blocks if blocks is not None else [TextBlock(type="text", text=text, citations=None)]
    return Message(
        id="msg_1",
        content=content,
        model="claude-haiku-5-5",
        role="assistant",
        stop_reason=stop,
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=inp, output_tokens=out),
    )


def make_llm(create, usage=None, **settings):
    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return AnthropicLLM(make_settings(anthropic_api_key="k", **settings), usage, client=client)


async def call(llm, user=f"hello {SECRET_PROMPT}", max_output_tokens=4096):
    return await llm.generate_structured(
        system="sys prompt",
        user=user,
        schema=TitleLabel,
        purpose="title_classification",
        max_output_tokens=max_output_tokens,
    )


async def test_request_uses_structured_outputs_with_the_transformed_schema():
    create = AsyncMock(return_value=message(VALID, inp=321, out=54))
    usage = RecordingUsage()
    llm = make_llm(create, usage, anthropic_model="claude-haiku-5-5")

    result = await call(llm)

    assert isinstance(result, TitleLabel) and result.level.value == "senior"
    kw = create.await_args.kwargs
    assert kw["model"] == "claude-haiku-5-5"
    assert kw["system"] == "sys prompt"
    assert kw["messages"] == [{"role": "user", "content": f"hello {SECRET_PROMPT}"}]
    assert kw["max_tokens"] == 4096 + THINKING_HEADROOM
    fmt = kw["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    schema = fmt["schema"]
    assert schema == anthropic.transform_schema(TitleLabel)
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["Item"]["additionalProperties"] is False
    assert schema["$defs"]["Level"]["enum"][0] == "junior"
    # parameters the current models reject, or that would be wrong for a JSON task
    for forbidden in (
        "temperature",
        "top_p",
        "top_k",
        "thinking",
        "tool_choice",
        "tools",
        "output_format",
        "prefill",
    ):
        assert forbidden not in kw
    assert "effort" not in kw["output_config"]

    (rec,) = usage.records
    assert (rec.provider, rec.model, rec.purpose) == (
        "anthropic",
        "claude-haiku-5-5",
        "title_classification",
    )
    assert (rec.input_tokens, rec.output_tokens, rec.success) == (321, 54, True)


async def test_thinking_blocks_before_the_text_are_skipped():
    blocks = [
        ThinkingBlock(type="thinking", thinking="", signature="s"),
        TextBlock(type="text", text=VALID, citations=None),
    ]
    create = AsyncMock(return_value=message("", blocks=blocks))
    assert (await call(make_llm(create))).title == "VP Sales"


async def test_one_retry_on_invalid_json_then_success():
    create = AsyncMock(side_effect=[message("not json at all"), message(VALID)])
    usage = RecordingUsage()
    await call(make_llm(create, usage))

    assert create.await_count == 2
    first, second = (c.kwargs["messages"][0]["content"] for c in create.await_args_list)
    assert second.startswith(first) and "rejected" in second
    assert [r.success for r in usage.records] == [False, True]


async def test_persistent_schema_violation_raises_without_echoing_content():
    bad = f'{{"title": "{SECRET_PROMPT}", "level": 12}}'
    create = AsyncMock(return_value=message(bad))
    usage = RecordingUsage()
    with pytest.raises(LLMError) as exc:
        await call(make_llm(create, usage))
    assert create.await_count == 2
    assert SECRET_PROMPT not in str(exc.value)
    assert all(SECRET_PROMPT not in (r.error or "") for r in usage.records)


async def test_refusal_is_not_retried_and_reports_the_category():
    refusal = message("", stop="refusal", blocks=[])
    refusal.stop_details = SimpleNamespace(type="refusal", category="cyber", explanation="x")
    create = AsyncMock(return_value=refusal)
    usage = RecordingUsage()
    with pytest.raises(LLMError, match="declined.*cyber"):
        await call(make_llm(create, usage))
    assert create.await_count == 1
    assert usage.records[0].success is False


async def test_truncated_output_is_not_retried():
    create = AsyncMock(return_value=message('{"one_liner": "x', stop="max_tokens"))
    with pytest.raises(LLMError, match="truncated"):
        await call(make_llm(create))
    assert create.await_count == 1


async def test_sdk_errors_are_wrapped_without_the_message():
    create = AsyncMock(side_effect=anthropic.AnthropicError(f"boom {SECRET_PROMPT}"))
    usage = RecordingUsage()
    with pytest.raises(LLMError) as exc:
        await call(make_llm(create, usage))
    assert SECRET_PROMPT not in str(exc.value) and "AnthropicError" in str(exc.value)
    assert SECRET_PROMPT not in usage.records[0].error


async def test_explanation_purpose_is_recorded():
    create = AsyncMock(return_value=message(VALID))
    usage = RecordingUsage()
    out = await make_llm(create, usage).generate_structured(
        system="s", user="u", schema=TitleLabel, purpose="explanation"
    )
    assert out.items == [] and usage.records[0].purpose == "explanation"


def test_missing_key_names_the_env_var_and_client_is_configured_from_settings():
    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY"):
        AnthropicLLM(make_settings())
    client = make_anthropic_client(make_settings(anthropic_api_key="sk-ant-xyz", llm_timeout_s=12))
    assert client.timeout == 12 and client.max_retries == 2
    assert client.api_key == "sk-ant-xyz"


async def test_aclose_closes_the_sdk_client():
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()), close=AsyncMock())
    await AnthropicLLM(make_settings(anthropic_api_key="k"), client=client).aclose()
    client.close.assert_awaited_once()
