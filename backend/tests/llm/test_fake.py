"""FakeLLM (generic) / FakeEmbedder: deterministic and offline."""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import BaseModel, Field

from app.llm.errors import LLMError
from app.llm.fake import FakeEmbedder, FakeLLM, _bucket, fold
from tests.llm.helpers import Item, Level, RecordingUsage, TitleLabel, sample_label


async def gen(llm, schema, purpose="title_classification"):
    return await llm.generate_structured(system="s", user="u", schema=schema, purpose=purpose)


async def test_generic_instance_is_valid_deterministic_and_uses_first_enum_member():
    a, b = await gen(FakeLLM(), TitleLabel), await gen(FakeLLM(), TitleLabel)
    assert a == b and isinstance(a, TitleLabel)
    assert a.level is Level.JUNIOR and a.title.startswith("fake-") and a.items == []


async def test_nested_required_lists_optionals_and_constraints():
    class Inner(BaseModel):
        name: str = Field(min_length=3)
        n: int

    class Outer(BaseModel):
        inners: list[Inner]
        maybe: str | None
        tags: list[str] = Field(default_factory=list)
        flag: bool

    out = await gen(FakeLLM(), Outer, "theme_naming")
    assert len(out.inners) == 1 and out.inners[0].name.startswith("fake-")
    assert out.maybe is None and out.tags == [] and out.flag is False
    assert out == await gen(FakeLLM(), Outer, "theme_naming")


async def test_register_overrides_a_schema_and_validates_handler_output():
    llm = FakeLLM()
    llm.register(TitleLabel, lambda system, user: sample_label(title=user))
    assert (await gen(llm, TitleLabel)).title == "u"
    llm.register(TitleLabel, lambda system, user: {"title": 1})
    with pytest.raises(LLMError, match="handler output invalid"):
        await gen(llm, TitleLabel)


async def test_records_usage_and_failure():
    usage = RecordingUsage()
    llm = FakeLLM(usage)
    await gen(llm, TitleLabel, "explanation")
    llm.register(TitleLabel, lambda s, u: {})
    with pytest.raises(LLMError):
        await gen(llm, TitleLabel)
    assert [r.success for r in usage.records] == [True, False]
    assert usage.records[0].purpose == "explanation" and usage.records[0].provider == "fake"


def test_item_schema_importable():
    assert Item(quote="q", source_id="s").source_id == "s"


def test_fold_keeps_length_so_indexes_map_back():
    text = "Équipe Œuvre ÇA va İstanbul"
    assert len(fold(text)) == len(text)
    assert fold("Réservez une DÉMO") == "reservez une demo"


# --- embedder ------------------------------------------------------------------------------------


async def test_embedder_shape_norm_and_determinism():
    e1, e2 = FakeEmbedder(dim=64), FakeEmbedder(dim=64)
    v1 = await e1.embed(["plateforme saas banque", "boulangerie pain"])
    v2 = await e2.embed(["plateforme saas banque", "boulangerie pain"])
    assert v1 == v2
    assert len(v1) == 2 and all(len(v) == 64 for v in v1)
    assert all(np.linalg.norm(v) == pytest.approx(1.0) for v in v1)
    assert (e1.name, e1.model, e1.dim) == ("fake", "fake-hash-v1", 64)


def test_embedder_hash_is_stable_across_processes():
    # blake2b, not Python's randomized hash(): pin two buckets so a change is noticed
    assert _bucket("cloud", 768) == _bucket("cloud", 768)
    idx, sign = _bucket("cloud", 768)
    assert 0 <= idx < 768 and sign in (-1.0, 1.0)
    assert (idx, sign) == (581, -1.0)


async def test_similar_texts_score_higher_than_unrelated_ones():
    emb = FakeEmbedder(dim=768)
    seed, close, far = await emb.embed(
        [
            "Offering: CRM platform for banks\nIndustries served: banking, insurance\n"
            "Keywords: crm",
            "Offering: sales platform for banks and insurers\nIndustries served: banking, "
            "insurance\nKeywords: crm, sales",
            "Offering: artisan bakery bread and pastries\nIndustries served: food\nKeywords: bread",
        ]
    )
    cos = lambda a, b: float(np.dot(a, b))  # noqa: E731
    assert cos(seed, close) > 0.4
    assert cos(seed, close) > cos(seed, far) + 0.3
    assert abs(cos(seed, far)) < 0.15


async def test_embedder_template_labels_do_not_create_similarity():
    emb = FakeEmbedder(dim=768)
    a, b = await emb.embed(
        ["Offering: alpha beta\nSales motion: gamma", "Offering: delta epsilon\nSales motion: zeta"]
    )
    assert abs(float(np.dot(a, b))) < 0.15


async def test_embedder_handles_empty_and_accented_text_and_records_usage():
    usage = RecordingUsage()
    emb = FakeEmbedder(dim=32, usage=usage)
    v_empty, v_acc, v_plain = await emb.embed(["", "électricité énergie", "electricite energie"])
    assert np.linalg.norm(v_empty) == pytest.approx(1.0)
    assert v_acc == v_plain  # accents folded
    assert usage.records[0].purpose == "embedding" and usage.records[0].provider == "fake"
