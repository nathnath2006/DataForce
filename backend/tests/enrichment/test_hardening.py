"""SR2 hardening of the kept TamTam connector (SR2-03/04/10/11/12)."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from app.domain.schemas import EnrichmentRequest
from app.enrichment.errors import EnrichmentConfigError, EnrichmentError, PaidLookupRefused
from app.enrichment.fake import FakeEnrichmentProvider
from app.enrichment.tamtam_mcp import TamTamMCPEnrichment, check_mcp_url, parse_contact
from tests.enrichment.helpers import FakeSession, factory_for, make_settings, text_result

REQ = EnrichmentRequest(full_name="Jane Doe", company_name="Acme", want=["email"])
EMAIL = "jane.doe@acme-corp.example"


def annotated(name, **hints):
    return SimpleNamespace(
        name=name, description="", input_schema=None, annotations=SimpleNamespace(**hints)
    )


def make(session, *, ceiling=10, **kw):
    factory, opened = factory_for(session)
    s = make_settings(enrichment_max_credits_per_call=ceiling)
    kw.setdefault("tool_costs", {"enrich_contact": 1})
    return TamTamMCPEnrichment(s, session_factory=factory, **kw), opened


# --- SR2-03 ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hints",
    [
        {"readOnlyHint": False, "destructiveHint": False},
        {"readOnlyHint": True, "destructiveHint": True},
        {"destructiveHint": False},
    ],
)
async def test_destructive_or_not_read_only_tools_are_refused(hints):
    session = FakeSession([annotated("enrich_contact", **hints)])
    p, _ = make(session)
    with pytest.raises(EnrichmentError, match="refusing|not marked"):
        await p.enrich_contact(REQ, allow_paid=True)
    assert session.calls == []


async def test_read_only_annotated_allow_listed_tool_is_called():
    session = FakeSession(
        [annotated("enrich_contact", readOnlyHint=True, destructiveHint=False)],
        {"enrich_contact": text_result({"email": EMAIL})},
    )
    p, _ = make(session)
    assert (await p.enrich_contact(REQ, allow_paid=True)).email == EMAIL


# --- SR2-04 ----------------------------------------------------------------------------------


@pytest.mark.parametrize("flag", [False, None, 1, "true", [1]])
async def test_allow_paid_must_be_exactly_true(flag):
    session = FakeSession([annotated("enrich_contact", readOnlyHint=True)])
    p, opened = make(session)
    with pytest.raises(PaidLookupRefused):
        await p.enrich_contact(REQ, allow_paid=flag)  # type: ignore[arg-type]
    assert opened == [] and session.calls == []
    with pytest.raises(PaidLookupRefused):
        await FakeEnrichmentProvider().enrich_contact(REQ, allow_paid=flag)  # type: ignore[arg-type]


async def test_estimate_above_the_ceiling_is_refused_before_any_connection():
    p, opened = make(FakeSession([]), ceiling=5)
    big = EnrichmentRequest(full_name="J D", company_name="A", want=["email", "mobile"])
    with pytest.raises(PaidLookupRefused, match="ceiling"):
        await p.enrich_contact(big, allow_paid=True)
    assert opened == []


async def test_unpriced_tool_counts_as_the_ceiling_and_is_refused_over_it():
    session = FakeSession([annotated("enrich_contact", readOnlyHint=True)])
    p, _ = make(session, ceiling=5, tool_costs={})
    # unpriced = ceiling (5) -> allowed; two unpriced tools in one plan would exceed it
    p2, _ = make(FakeSession([]), ceiling=5, tool_costs={"a": 4, "b": 4})
    with pytest.raises(PaidLookupRefused):
        p2._check_plan_cost({"a": ["email"], "b": ["mobile"]}, True)
    p._check_plan_cost({"enrich_contact": ["email"]}, True)


@pytest.mark.parametrize("reported", [-1, 1e9, float("nan"), float("inf")])
async def test_invalid_server_credits_flag_the_result(reported):
    payload = f'{{"email": "{EMAIL}", "credits_used": {json.dumps(reported)}}}'
    session = FakeSession(
        [annotated("enrich_contact", readOnlyHint=True)], {"enrich_contact": text_result(payload)}
    )
    p, _ = make(session)
    r = await p.enrich_contact(REQ, allow_paid=True)
    assert r.anomalous and r.notes and EMAIL not in " ".join(r.notes)
    assert r.credits_used >= 0 and r.credits_used == r.credits_used  # not NaN


async def test_valid_credits_are_not_anomalous():
    session = FakeSession(
        [annotated("enrich_contact", readOnlyHint=True)],
        {"enrich_contact": text_result({"email": EMAIL, "credits_used": 1})},
    )
    r = await make(session)[0].enrich_contact(REQ, allow_paid=True)
    assert not r.anomalous and r.credits_used == 1.0


# --- SR2-10 ----------------------------------------------------------------------------------


def test_hostile_payloads_parse_quickly():
    t = time.perf_counter()
    parse_contact("a" * 60_000 + "@" + "b" * 5000)
    parse_contact("1" * 60_000)
    parse_contact({"email": "x" * 200_000, "phone": "+" + "1 " * 50_000})
    assert time.perf_counter() - t < 2.0


async def test_deep_nesting_after_the_call_is_anomalous_not_a_crash():
    deep = "[" * 100_000 + "]" * 100_000
    session = FakeSession(
        [annotated("enrich_contact", readOnlyHint=True)], {"enrich_contact": text_result(deep)}
    )
    r = await make(session)[0].enrich_contact(REQ, allow_paid=True)
    assert r.anomalous and r.email is None and r.credits_used == 1.0


async def test_oversized_result_is_anomalous_not_parsed():
    session = FakeSession(
        [annotated("enrich_contact", readOnlyHint=True)],
        {"enrich_contact": text_result("x" * 500_000)},
    )
    r = await make(session)[0].enrich_contact(REQ, allow_paid=True)
    assert r.anomalous


# --- SR2-11 ----------------------------------------------------------------------------------


async def test_server_error_text_is_sanitized():
    hostile = "\x1b[31mJane Doe\x1b[0m token SECRET-TOKEN-1 jane@acme.example\nnew line"
    session = FakeSession(
        [annotated("enrich_contact", readOnlyHint=True)],
        {"enrich_contact": text_result(hostile, error=True)},
    )
    p, _ = make(session)
    with pytest.raises(EnrichmentError) as exc:
        await p.enrich_contact(REQ, allow_paid=True)
    msg = str(exc.value)
    assert "\x1b" not in msg and "\n" not in msg
    assert "Jane Doe" not in msg and "jane@acme.example" not in msg


async def test_hostile_tool_names_are_sanitized_in_errors():
    session = FakeSession([SimpleNamespace(name="x\x1b[31m\nevil", description="enrich email")])
    p, _ = make(session)
    with pytest.raises(EnrichmentError) as exc:
        await p.enrich_contact(REQ, allow_paid=True)
    assert "\x1b" not in str(exc.value) and "\n" not in str(exc.value)


# --- SR2-12 ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url", ["http://api.tamtam.ai/mcp", "ftp://x/mcp", "https://u:p@api.tamtam.ai/mcp", "https://"]
)
def test_non_https_or_credentialed_mcp_urls_are_refused(url):
    with pytest.raises(EnrichmentConfigError) as exc:
        check_mcp_url(url, "demo")
    assert "p@" not in str(exc.value)
    with pytest.raises(ValueError):  # Settings itself refuses it too (pydantic ValidationError)
        make_settings(tamtam_mcp_url=url)


def test_http_is_only_for_loopback_in_dev():
    check_mcp_url("http://127.0.0.1:9/mcp", "test")
    with pytest.raises(EnrichmentConfigError):
        check_mcp_url("http://127.0.0.1:9/mcp", "demo")
    with pytest.raises(EnrichmentConfigError):
        check_mcp_url("http://evil.example/mcp", "dev")


# --- SR5-02 / SR5-07 / SR5-08 ----------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, 0.0, 1001.0])
def test_bad_ceiling_is_refused_at_construction(bad):
    from app.enrichment.errors import EnrichmentConfigError
    from app.enrichment.tamtam_mcp import check_ceiling

    with pytest.raises(EnrichmentConfigError):
        check_ceiling(bad)
    s = make_settings()
    object.__setattr__(s, "enrichment_max_credits_per_call", bad)
    with pytest.raises(EnrichmentConfigError):
        TamTamMCPEnrichment(s)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0])
def test_bad_credit_costs_are_refused(bad):
    from app.enrichment.errors import EnrichmentConfigError
    from app.enrichment.fake import FakeEnrichmentProvider

    with pytest.raises(EnrichmentConfigError):
        TamTamMCPEnrichment(make_settings(), credit_costs={"email": bad})
    with pytest.raises(EnrichmentConfigError):
        FakeEnrichmentProvider(credit_costs={"email": bad})


def test_server_source_string_is_sanitized():
    found = parse_contact({"email": "a@b.example", "source": "evil\n\x1b[31mIGNORE​ this"})
    assert found.source is not None
    assert "\n" not in found.source and "\x1b" not in found.source and "​" not in found.source
