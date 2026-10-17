"""GeminiLLM / GeminiEmbedder with the google-genai client mocked (real SDK types, no network)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from app.llm.errors import LLMConfigError, LLMError
from app.llm.gemini import (
    EMBED_BATCH_SIZE,
    GeminiEmbedder,
    GeminiLLM,
    gemini_json_schema,
    make_gemini_client,
)
from tests.llm.helpers import RecordingUsage, TitleLabel, make_settings, sample_label

SECRET_PROMPT = "TOP-SECRET-PROMPT-MARKER-12345"


def gemini_response(text, *, prompt=10, out=5, thoughts=None, finish="STOP"):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=text)]),
                finish_reason=finish,
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt, candidates_token_count=out, thoughts_token_count=thoughts
        ),
    )


def fake_client(generate=None, embed=None):
    models = SimpleNamespace(
        generate_content=generate or AsyncMock(), embed_content=embed or AsyncMock()
    )
    return SimpleNamespace(aio=SimpleNamespace(models=models))


def make_llm(client, usage=None, **settings):
    s = make_settings(gemini_api_key="k", **settings)
    return GeminiLLM(s, usage, client=client)


VALID = sample_label().model_dump_json()


async def call(llm, user=f"hello {SECRET_PROMPT}"):
    return await llm.generate_structured(
        system="sys prompt", user=user, schema=TitleLabel, purpose="title_classification"
    )


# --- structured output ---------------------------------------------------------------------------


async def test_request_parameters_and_validated_result():
    generate = AsyncMock(return_value=gemini_response(VALID, prompt=123, out=45, thoughts=6))
    usage = RecordingUsage()
    llm = make_llm(fake_client(generate), usage, gemini_model="gemini-2.5-flash")

    result = await call(llm)

    assert isinstance(result, TitleLabel) and result.title == "VP Sales"
    kwargs = generate.await_args.kwargs
    assert kwargs["model"] == "gemini-2.5-flash"
    assert kwargs["contents"] == f"hello {SECRET_PROMPT}"
    cfg = kwargs["config"]
    assert cfg.system_instruction == "sys prompt"
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_schema is None
    assert cfg.response_json_schema == gemini_json_schema(TitleLabel)
    assert cfg.temperature == 0.0
    assert cfg.max_output_tokens == 4096  # thinking disabled on 2.5 flash: no headroom needed
    assert cfg.thinking_config.thinking_budget == 0

    (rec,) = usage.records
    assert (rec.provider, rec.model, rec.purpose) == (
        "gemini",
        "gemini-2.5-flash",
        "title_classification",
    )
    assert rec.input_tokens == 123 and rec.output_tokens == 45 + 6  # thinking is billed as output
    assert rec.success is True and rec.error is None and rec.latency_ms >= 0


def test_json_schema_keeps_enums_nested_lists_and_drops_unsupported_keywords():
    schema = gemini_json_schema(TitleLabel)
    defs = schema["$defs"]
    assert defs["Level"]["enum"] == ["junior", "senior"]
    assert defs["Item"]["properties"]["quote"]["type"] == "string"
    assert schema["properties"]["items"]["type"] == "array"
    assert schema["properties"]["items"]["items"] == {"$ref": "#/$defs/Item"}
    assert schema["properties"]["level"] == {"$ref": "#/$defs/Level"}
    assert "confidence" in schema["required"]
    assert "items" not in schema["required"]

    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from (
                    keys(v)
                    if k not in ("properties", "$defs")
                    else (kk for sub in v.values() for kk in keys(sub))
                )
        elif isinstance(node, list):
            for x in node:
                yield from keys(x)

    assert not {"title", "default"} & set(keys(schema))


def test_json_schema_does_not_drop_fields_named_title_or_default():
    class M(BaseModel):
        title: str
        default: int = 3

    schema = gemini_json_schema(M)
    assert set(schema["properties"]) == {"title", "default"}
    assert "default" not in schema["properties"]["default"]


async def test_pydantic_schema_mode_passes_the_class():
    generate = AsyncMock(return_value=gemini_response(VALID))
    llm = GeminiLLM(
        make_settings(gemini_api_key="k"), client=fake_client(generate), schema_mode="pydantic"
    )
    await call(llm)
    cfg = generate.await_args.kwargs["config"]
    assert cfg.response_schema is TitleLabel and cfg.response_json_schema is None


async def test_thinking_models_get_output_headroom_and_no_zero_budget():
    generate = AsyncMock(return_value=gemini_response(VALID))
    await call(make_llm(fake_client(generate), gemini_model="gemini-2.5-pro"))
    cfg = generate.await_args.kwargs["config"]
    assert cfg.thinking_config is None
    assert cfg.max_output_tokens > 4096


async def test_one_retry_on_invalid_json_then_success_with_two_usage_records():
    generate = AsyncMock(
        side_effect=[
            gemini_response('{"title": "x"', prompt=100, out=3),  # truncated / invalid
            gemini_response(VALID, prompt=110, out=40),
        ]
    )
    usage = RecordingUsage()
    result = await call(make_llm(fake_client(generate), usage))

    assert result.level.value == "senior"
    assert generate.await_count == 2
    first, second = (c.kwargs["contents"] for c in generate.await_args_list)
    assert first == f"hello {SECRET_PROMPT}"
    assert second.startswith(first) and "rejected" in second and "JSON" in second
    assert [r.success for r in usage.records] == [False, True]
    assert usage.records[0].input_tokens == 100
    assert usage.records[0].error and "invalid structured output" in usage.records[0].error


async def test_schema_violation_is_retried_and_error_never_echoes_content():
    bad = f'{{"title": "{SECRET_PROMPT}", "level": "not-an-enum"}}'
    generate = AsyncMock(return_value=gemini_response(bad))
    usage = RecordingUsage()
    with pytest.raises(LLMError) as exc:
        await call(make_llm(fake_client(generate), usage))

    assert generate.await_count == 2  # exactly one retry
    assert SECRET_PROMPT not in str(exc.value)
    assert "level" in str(exc.value)  # field path + error type are fine
    assert all(SECRET_PROMPT not in (r.error or "") for r in usage.records)
    assert [r.success for r in usage.records] == [False, False]


async def test_empty_response_is_an_invalid_output_with_finish_reason():
    resp = types.GenerateContentResponse(
        candidates=[types.Candidate(finish_reason="SAFETY")],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=4),
    )
    usage = RecordingUsage()
    with pytest.raises(LLMError, match="SAFETY"):
        await call(make_llm(fake_client(AsyncMock(return_value=resp)), usage))
    assert "empty response" in usage.records[0].error and "SAFETY" in usage.records[0].error


async def test_json_fence_is_tolerated():
    generate = AsyncMock(return_value=gemini_response(f"```json\n{VALID}\n```"))
    assert (await call(make_llm(fake_client(generate)))).title == "VP Sales"


async def test_sdk_error_is_wrapped_without_message_or_prompt():
    exc = genai_errors.ClientError(
        400,
        {"error": {"message": f"bad request near {SECRET_PROMPT}", "status": "INVALID_ARGUMENT"}},
    )
    usage = RecordingUsage()
    with pytest.raises(LLMError) as raised:
        await call(make_llm(fake_client(AsyncMock(side_effect=exc)), usage))
    msg = str(raised.value)
    assert SECRET_PROMPT not in msg
    assert "ClientError" in msg and "400" in msg and "INVALID_ARGUMENT" in msg
    assert raised.value.__cause__ is None  # SR2-15
    (rec,) = usage.records
    assert rec.success is False and SECRET_PROMPT not in rec.error
    assert len(usage.records) == 1  # API errors are not retried by us (the SDK retries 429/5xx)


async def test_timeout_comes_from_settings():
    async def slow(**_):
        await asyncio.sleep(5)

    usage = RecordingUsage()
    llm = make_llm(fake_client(AsyncMock(side_effect=slow)), usage, llm_timeout_s=0.05)
    with pytest.raises(LLMError, match="no response within"):
        await call(llm)
    assert usage.records[0].success is False


async def test_concurrency_is_limited_by_settings():
    active = peak = 0

    async def tracked(**_):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return gemini_response(VALID)

    llm = make_llm(fake_client(AsyncMock(side_effect=tracked)), llm_max_concurrency=2)
    await asyncio.gather(*(call(llm) for _ in range(8)))
    assert peak == 2


async def test_a_failing_usage_recorder_does_not_break_the_call():
    class Boom:
        def record(self, call):
            raise RuntimeError("db down")

    llm = make_llm(fake_client(AsyncMock(return_value=gemini_response(VALID))), Boom())
    assert (await call(llm)).title


# --- client construction -------------------------------------------------------------------------


def test_missing_key_raises_config_error_naming_the_env_var():
    with pytest.raises(LLMConfigError, match="GEMINI_API_KEY"):
        GeminiLLM(make_settings())
    with pytest.raises(LLMConfigError, match="GEMINI_API_KEY"):
        GeminiEmbedder(make_settings(gemini_api_key=""))


def test_client_gets_the_key_a_timeout_in_ms_and_never_vertex():
    s = make_settings(gemini_api_key="sk-test-123", llm_timeout_s=7.5)
    client = make_gemini_client(s)
    assert client.vertexai is False
    assert client._api_client.api_key == "sk-test-123"
    assert client._api_client._http_options.timeout == 7500
    assert "sk-test-123" not in repr(s)


# --- embeddings ----------------------------------------------------------------------------------


def embed_response(vectors):
    return types.EmbedContentResponse(
        embeddings=[types.ContentEmbedding(values=v) for v in vectors]
    )


def make_embedder(embed, usage=None, **settings):
    s = make_settings(gemini_api_key="k", **settings)
    return GeminiEmbedder(s, usage, client=fake_client(embed=embed))


async def test_embedding_request_parameters_normalization_and_usage():
    embed = AsyncMock(return_value=embed_response([[3.0, 4.0, 0.0, 0.0], [0.0, 0.0, 0.0, 2.0]]))
    usage = RecordingUsage()
    emb = make_embedder(
        embed, usage, embedding_dim=4, gemini_embedding_model="gemini-embedding-001"
    )

    vectors = await emb.embed(["a", "b"])

    kwargs = embed.await_args.kwargs
    assert kwargs["model"] == "gemini-embedding-001"
    assert kwargs["contents"] == ["a", "b"]
    assert kwargs["config"].task_type == "SEMANTIC_SIMILARITY"
    assert kwargs["config"].output_dimensionality == 4
    assert vectors[0] == pytest.approx([0.6, 0.8, 0.0, 0.0])
    assert vectors[1] == pytest.approx([0.0, 0.0, 0.0, 1.0])
    for v in vectors:
        assert np.linalg.norm(v) == pytest.approx(1.0)
    assert (emb.name, emb.model, emb.dim) == ("gemini", "gemini-embedding-001", 4)
    (rec,) = usage.records
    assert rec.purpose == "embedding" and rec.success and rec.provider == "gemini"


async def test_embeddings_are_batched_by_100_and_order_is_preserved():
    sizes = []

    async def fake_embed(*, model, contents, config):
        sizes.append(len(contents))
        return embed_response([[float(int(t)) + 1.0, 0.0] for t in contents])

    emb = make_embedder(AsyncMock(side_effect=fake_embed), RecordingUsage(), embedding_dim=2)
    texts = [str(i) for i in range(250)]
    vectors = await emb.embed(texts)

    assert EMBED_BATCH_SIZE == 100
    assert sizes == [100, 100, 50]
    assert len(vectors) == 250
    assert all(v == pytest.approx([1.0, 0.0]) for v in vectors)  # normalized: direction only


async def test_wrong_dimension_is_rejected():
    emb = make_embedder(
        AsyncMock(return_value=embed_response([[1.0, 0.0, 0.0]])), RecordingUsage(), embedding_dim=2
    )
    with pytest.raises(LLMError, match="3 dimensions, expected 2"):
        await emb.embed(["x"])


async def test_wrong_count_zero_vector_and_empty_text_are_rejected():
    with pytest.raises(LLMError, match="expected 2 embeddings"):
        await make_embedder(
            AsyncMock(return_value=embed_response([[1.0, 0.0]])), embedding_dim=2
        ).embed(["a", "b"])
    with pytest.raises(LLMError, match="zero"):
        await make_embedder(
            AsyncMock(return_value=embed_response([[0.0, 0.0]])), embedding_dim=2
        ).embed(["a"])
    with pytest.raises(LLMError, match="empty"):
        await make_embedder(AsyncMock(), embedding_dim=2).embed(["a", "  "])


async def test_embedding_sdk_error_is_wrapped_and_recorded():
    usage = RecordingUsage()
    emb = make_embedder(AsyncMock(side_effect=RuntimeError(SECRET_PROMPT)), usage, embedding_dim=2)
    with pytest.raises(LLMError) as exc:
        await emb.embed(["x"])
    assert SECRET_PROMPT not in str(exc.value) and "RuntimeError" in str(exc.value)
    assert usage.records[0].success is False and SECRET_PROMPT not in usage.records[0].error


async def test_no_texts_means_no_call():
    embed = AsyncMock()
    assert await make_embedder(embed, embedding_dim=2).embed([]) == []
    embed.assert_not_awaited()


# --- wire format through the real SDK (only the HTTP call is replaced) ---------------------------


def _client_capturing_http(settings, body_for):
    sent = []
    client = make_gemini_client(settings)

    async def fake_request(http_method, path, request_dict, http_options=None):
        sent.append((http_method, path, request_dict))
        return types.HttpResponse(headers={}, body=json.dumps(body_for(path, request_dict)))

    client.aio.models._api_client.async_request = fake_request
    return client, sent


async def test_generate_content_wire_format():
    def body(path, request):
        return {
            "candidates": [{"content": {"parts": [{"text": VALID}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 9},
        }

    s = make_settings(gemini_api_key="k", gemini_model="gemini-2.5-flash")
    client, sent = _client_capturing_http(s, body)
    usage = RecordingUsage()
    result = await GeminiLLM(s, usage, client=client).generate_structured(
        system="SYS", user="USER", schema=TitleLabel, purpose="title_classification"
    )

    assert result.title == "VP Sales"
    ((method, path, req),) = sent
    assert (method, path) == ("post", "models/gemini-2.5-flash:generateContent")
    assert req["systemInstruction"]["parts"] == [{"text": "SYS"}]
    assert req["contents"][0]["parts"] == [{"text": "USER"}]
    cfg = req["generationConfig"]
    assert cfg["responseMimeType"] == "application/json"
    assert cfg["responseJsonSchema"] == gemini_json_schema(TitleLabel)
    # the SDK serializes nested config with the proto field name; the API accepts both spellings
    assert list(cfg["thinkingConfig"].values()) == [0]
    assert cfg["maxOutputTokens"] == 4096 and cfg["temperature"] == 0.0
    assert (usage.records[0].input_tokens, usage.records[0].output_tokens) == (7, 9)


async def test_embed_content_wire_format():
    def body(path, request):
        return {"embeddings": [{"values": [3.0, 4.0]} for _ in request["requests"]]}

    s = make_settings(gemini_api_key="k", embedding_dim=2)
    client, sent = _client_capturing_http(s, body)
    vectors = await GeminiEmbedder(s, client=client).embed(["a", "b"])

    ((_, path, req),) = sent
    assert path == "models/gemini-embedding-001:batchEmbedContents"
    assert [r["taskType"] for r in req["requests"]] == ["SEMANTIC_SIMILARITY"] * 2
    assert [r["outputDimensionality"] for r in req["requests"]] == [2, 2]
    assert [r["content"]["parts"][0]["text"] for r in req["requests"]] == ["a", "b"]
    assert vectors == [pytest.approx([0.6, 0.8])] * 2


async def test_aclose_closes_the_sdk_clients():
    client = fake_client()
    client.aio.aclose = AsyncMock()
    await make_llm(client).aclose()
    emb = GeminiEmbedder(make_settings(gemini_api_key="k"), client=client)
    await emb.aclose()
    assert client.aio.aclose.await_count == 2
