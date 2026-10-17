"""TamTamMCPEnrichment with a mocked MCP session: paid guard, tool discovery, parsing."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.domain.ports import EnrichmentProvider
from app.domain.schemas import EnrichmentRequest
from app.enrichment.errors import EnrichmentConfigError, EnrichmentError, PaidLookupRefused
from app.enrichment.tamtam_mcp import (
    DEFAULT_CREDIT_COSTS,
    DEFAULT_TOOL_MAP,
    TamTamMCPEnrichment,
    ToolInfo,
    parse_contact,
)
from tests.enrichment.helpers import FakeSession, factory_for, make_settings, text_result, tool

EMAIL = "jane.doe@acme-corp.example"
MOBILE = "+33 6 39 98 12 34"


def req(**kw):
    base = {
        "full_name": "Jane Doe",
        "company_name": "Acme",
        "company_domain": "acme.fr",
        "want": ["email"],
    }
    base.update(kw)
    return EnrichmentRequest(**base)


TOOL_COSTS = {"enrich_contact": 11, "find_email": 1, "find_phone": 10, "find_contact": 11}


def provider(session, **kw):
    factory, opened = factory_for(session)
    kw.setdefault("tool_costs", TOOL_COSTS)
    settings = make_settings(enrichment_max_credits_per_call=50)
    return TamTamMCPEnrichment(settings, session_factory=factory, **kw), opened


STD_TOOLS = [
    tool("search_companies", "Search companies by name"),
    tool(
        "enrich_contact",
        "Find a person's email or mobile",
        {
            "type": "object",
            "properties": {"full_name": {}, "company_name": {}, "company_domain": {}, "want": {}},
            "required": ["full_name", "company_name"],
        },
    ),
]


def std_session(payload=None):
    payload = payload or {"email": EMAIL, "mobile": MOBILE, "credits_used": 11}
    return FakeSession(STD_TOOLS, {"enrich_contact": text_result(payload)})


# --- assumptions are documented in code ----------------------------------------------------------


def test_assumed_costs_and_default_tool_names():
    assert DEFAULT_CREDIT_COSTS == {"email": 1.0, "mobile": 10.0}
    assert "enrich_contact" in DEFAULT_TOOL_MAP["email"]
    assert "find_contact" in DEFAULT_TOOL_MAP["mobile"]
    assert "enrich_person" in DEFAULT_TOOL_MAP["email"]
    doc = __import__("app.enrichment.tamtam_mcp", fromlist=["x"]).__doc__
    assert "https://api.tamtam.ai/mcp" in doc and "unverified" in doc and "OAuth" in doc


def test_satisfies_the_enrichment_provider_port():
    assert isinstance(TamTamMCPEnrichment(make_settings()), EnrichmentProvider)


# --- paid guard ----------------------------------------------------------------------------------


@pytest.mark.parametrize("want", [["email"], ["mobile"], ["email", "mobile"]])
async def test_paid_lookups_are_refused_before_any_connection(want):
    session = std_session()
    p, opened = provider(session)
    with pytest.raises(PaidLookupRefused) as exc:
        await p.enrich_contact(req(want=want), allow_paid=False)
    assert opened == [] and session.calls == []  # nothing was even connected
    assert "allow_paid" in str(exc.value) and "credit" in str(exc.value)


async def test_the_guard_does_not_need_a_token():
    p = TamTamMCPEnrichment(make_settings())  # no token, default session factory
    with pytest.raises(PaidLookupRefused):
        await p.enrich_contact(req(want=["mobile"]), allow_paid=False)


async def test_a_free_lookup_is_allowed_without_allow_paid():
    p, opened = provider(
        std_session(), credit_costs={"email": 0.0}, tool_costs={"enrich_contact": 0}
    )
    result = await p.enrich_contact(req(want=["email"]), allow_paid=False)
    assert result.email == EMAIL and opened == [1]
    with pytest.raises(PaidLookupRefused):  # mobile still costs
        await p.enrich_contact(req(want=["mobile"]), allow_paid=False)


def test_cost_estimate_uses_the_configurable_assumptions():
    p = TamTamMCPEnrichment(make_settings(), credit_costs={"mobile": 25})
    assert p.estimate_cost(["email", "mobile", "mobile"]) == 26.0


async def test_allow_paid_runs_the_lookup():
    session = std_session()
    p, opened = provider(session)
    result = await p.enrich_contact(req(want=["email", "mobile"]), allow_paid=True)
    assert opened == [1]
    assert (result.provider, result.email, result.mobile) == ("tamtam_mcp", EMAIL, MOBILE)
    assert result.credits_used == 11.0  # as reported by the tool
    assert result.raw_tool == "enrich_contact"
    ((name, args),) = session.calls  # one tool serves both fields => one call
    assert name == "enrich_contact"
    assert args == {
        "full_name": "Jane Doe",
        "company_name": "Acme",
        "company_domain": "acme.fr",
        "want": ["email", "mobile"],
    }


# --- tool discovery ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["enrich_contact", "find_contact", "enrich_person", "ENRICH_CONTACT"]
)
async def test_default_candidate_names_are_found(name):
    session = FakeSession([tool("noise"), tool(name)], {name: text_result({"email": EMAIL})})
    p, _ = provider(session)
    result = await p.enrich_contact(req(), allow_paid=True)
    assert result.email == EMAIL and session.calls[0][0] == name


async def test_tool_map_overrides_defaults_and_accepts_a_string():
    session = FakeSession(
        [tool("enrich_contact"), tool("my_custom_lookup")],
        {"my_custom_lookup": text_result({"email": EMAIL}), "enrich_contact": text_result({})},
    )
    p, _ = provider(session, tool_map={"email": "my_custom_lookup"})
    await p.enrich_contact(req(), allow_paid=True)
    assert session.calls[0][0] == "my_custom_lookup"


async def test_different_tools_per_field_are_both_called_and_merged():
    session = FakeSession(
        [tool("find_email"), tool("find_phone")],
        {
            "find_email": text_result({"email": EMAIL, "credits": 1}),
            "find_phone": text_result({"phone_number": MOBILE, "credits": 10}),
        },
    )
    p, _ = provider(session, tool_map={"email": ["find_email"], "mobile": ["find_phone"]})
    result = await p.enrich_contact(req(want=["email", "mobile"]), allow_paid=True)
    assert [c[0] for c in session.calls] == ["find_email", "find_phone"]
    assert (result.email, result.mobile, result.credits_used) == (EMAIL, MOBILE, 11.0)
    assert result.raw_tool == "find_email, find_phone"


async def test_keyword_match_is_only_a_suggestion_never_called(caplog):
    tools = [
        tool("list_campaigns", "List outreach campaigns"),
        tool("reveal_prospect_email", "Reveal the professional email address of a prospect"),
    ]
    session = FakeSession(tools, {"reveal_prospect_email": text_result({"email": EMAIL})})
    p, _ = provider(session)
    with pytest.raises(EnrichmentError, match="reveal_prospect_email"):
        await p.enrich_contact(req(), allow_paid=True)
    assert session.calls == []


async def test_no_matching_tool_lists_what_the_server_exposes():
    session = FakeSession([tool("search_companies", "x"), tool("get_weather", "y")])
    p, _ = provider(session)
    with pytest.raises(EnrichmentError) as exc:
        await p.enrich_contact(req(), allow_paid=True)
    msg = str(exc.value)
    assert "get_weather" not in msg and "tool_map" in msg and "2 tool(s)" in msg
    assert session.calls == []


async def test_server_with_no_tools_is_reported_clearly():
    p, _ = provider(FakeSession([]))
    with pytest.raises(EnrichmentError, match=r"0 tool"):
        await p.enrich_contact(req(), allow_paid=True)


def test_plan_groups_fields_by_tool():
    p = TamTamMCPEnrichment(make_settings())
    infos = [ToolInfo("enrich_contact", "", {})]
    assert p.plan(infos, ["email", "mobile"]) == {"enrich_contact": ["email", "mobile"]}


# --- argument mapping ----------------------------------------------------------------------------


async def test_first_and_last_name_schemas_are_filled():
    t = tool(
        "enrich_person",
        "",
        {
            "properties": {"first_name": {}, "last_name": {}, "organization": {}, "domain": {}},
            "required": ["first_name", "last_name"],
        },
    )
    session = FakeSession([t], {"enrich_person": text_result({"email": EMAIL})})
    p, _ = provider(session)
    await p.enrich_contact(req(full_name="Jane Van Doe"), allow_paid=True)
    assert session.calls[0][1] == {
        "first_name": "Jane",
        "last_name": "Van Doe",
        "organization": "Acme",
        "domain": "acme.fr",
    }


async def test_unfillable_required_argument_fails_before_calling_the_tool():
    t = tool(
        "enrich_contact", "", {"properties": {"linkedin_url": {}}, "required": ["linkedin_url"]}
    )
    session = FakeSession([t], {"enrich_contact": text_result({})})
    p, _ = provider(session)
    with pytest.raises(EnrichmentError, match="linkedin_url"):
        await p.enrich_contact(req(), allow_paid=True)
    assert session.calls == []


async def test_camel_case_input_schema_from_older_mcp_versions_is_understood():
    t = tool(
        "enrich_contact",
        "",
        {"properties": {"full_name": {}}, "required": ["full_name"]},
        camel=True,
    )
    session = FakeSession([t], {"enrich_contact": text_result({"email": EMAIL}, camel=True)})
    p, _ = provider(session)
    assert (await p.enrich_contact(req(), allow_paid=True)).email == EMAIL
    assert session.calls[0][1] == {"full_name": "Jane Doe"}


# --- result parsing ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "email", "mobile"),
    [
        ({"email": EMAIL, "mobile": MOBILE}, EMAIL, MOBILE),
        ({"data": {"work_email": EMAIL, "personal_email": "x@y.example"}}, EMAIL, None),
        (
            {
                "contact": {
                    "emails": [{"type": "work", "value": EMAIL}],
                    "phones": [{"type": "mobile", "number": MOBILE}],
                }
            },
            EMAIL,
            MOBILE,
        ),
        ({"result": f'{{"email": "{EMAIL}", "mobile_phone": "{MOBILE}"}}'}, EMAIL, MOBILE),
        ({"phone": "+33 1 23 45 67 89"}, None, "+33 1 23 45 67 89"),
        ({"phone": "n/a", "email": "not-an-email", "email_status": "verified"}, None, None),
        ({"status": "no match found"}, None, None),
        (f"Found: {EMAIL} / {MOBILE}", EMAIL, MOBILE),
        ("nothing here", None, None),
        ([], None, None),
        (None, None, None),
    ],
)
def test_parse_contact_is_defensive(payload, email, mobile):
    found = parse_contact(payload)
    assert (found.email, found.mobile) == (email, mobile)


def test_explicit_mobile_keys_win_over_generic_phone_keys():
    found = parse_contact({"phone": "+33 1 23 45 67 89", "mobile": MOBILE})
    assert found.mobile == MOBILE


async def test_structured_content_is_preferred_and_plain_text_is_tolerated():
    structured = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ignored")],
        is_error=False,
        structured_content={"email": EMAIL},
    )
    session = FakeSession(STD_TOOLS, {"enrich_contact": structured})
    p, _ = provider(session)
    assert (await p.enrich_contact(req(), allow_paid=True)).email == EMAIL

    session = FakeSession(STD_TOOLS, {"enrich_contact": text_result("Email: " + EMAIL)})
    p, _ = provider(session)
    assert (await p.enrich_contact(req(), allow_paid=True)).email == EMAIL


async def test_nothing_found_returns_an_empty_result_and_no_assumed_charge():
    p, _ = provider(std_session({"status": "not found"}))
    result = await p.enrich_contact(req(want=["email", "mobile"]), allow_paid=True)
    assert (result.email, result.mobile, result.credits_used) == (None, None, 0.0)


async def test_credits_fall_back_to_assumed_costs_of_delivered_fields_only():
    p, _ = provider(std_session({"email": EMAIL}))  # no credit info, no mobile
    result = await p.enrich_contact(req(want=["email", "mobile"]), allow_paid=True)
    assert result.email == EMAIL and result.mobile is None and result.credits_used == 1.0


async def test_fields_that_were_not_requested_are_dropped():
    p, _ = provider(std_session({"email": EMAIL, "mobile": MOBILE, "credits_used": 1}))
    result = await p.enrich_contact(req(want=["email"]), allow_paid=True)
    assert result.email == EMAIL and result.mobile is None


# --- errors and privacy --------------------------------------------------------------------------


async def test_tool_error_is_raised_with_contact_values_masked():
    err = text_result(f"lookup failed for {EMAIL} phone {MOBILE}", error=True)
    p, _ = provider(FakeSession(STD_TOOLS, {"enrich_contact": err}))
    with pytest.raises(EnrichmentError) as exc:
        await p.enrich_contact(req(), allow_paid=True)
    msg = str(exc.value)
    assert "enrich_contact" in msg and EMAIL not in msg and "12 34" not in msg and "***" in msg


async def test_transport_errors_are_wrapped_without_their_message():
    @asynccontextmanager
    async def boom():
        raise RuntimeError(f"connection reset while sending {EMAIL}")
        yield  # pragma: no cover

    p = TamTamMCPEnrichment(make_settings(), session_factory=boom)
    with pytest.raises(EnrichmentError) as exc:
        await p.enrich_contact(req(), allow_paid=True)
    assert "RuntimeError" in str(exc.value) and EMAIL not in str(exc.value)


async def test_auth_failures_get_an_actionable_message():
    class FakeHTTPError(Exception):
        response = SimpleNamespace(status_code=401)

    @asynccontextmanager
    async def denied():
        raise ExceptionGroup("unhandled errors in a TaskGroup", [FakeHTTPError("nope")])
        yield  # pragma: no cover

    p = TamTamMCPEnrichment(make_settings(), session_factory=denied)
    with pytest.raises(
        EnrichmentError, match=r"authentication rejected \(HTTP 401\).*TAMTAM_MCP_TOKEN"
    ):
        await p.enrich_contact(req(), allow_paid=True)


async def test_timeout_is_enforced():
    class Slow(FakeSession):
        async def list_tools(self):
            await asyncio.sleep(5)

    p, _ = provider(Slow([]), timeout_s=0.05)
    with pytest.raises(EnrichmentError, match="timed out"):
        await p.enrich_contact(req(), allow_paid=True)


async def test_missing_token_names_the_env_var():
    p = TamTamMCPEnrichment(make_settings())
    with pytest.raises(EnrichmentConfigError, match="TAMTAM_MCP_TOKEN"):
        await p.enrich_contact(req(), allow_paid=True)


async def test_contact_values_are_never_logged(caplog):
    caplog.set_level(logging.DEBUG)
    p, _ = provider(std_session())
    await p.enrich_contact(req(want=["email", "mobile"]), allow_paid=True)
    assert EMAIL not in caplog.text and "98 12 34" not in caplog.text
    assert "found_email=True" in caplog.text  # booleans only


async def test_keyword_fallback_never_picks_search_or_mutating_tools():
    tools = [
        tool("search_people", "Search people and contacts to find and enrich leads"),
        tool("update_contact", "Find and update a contact record"),
        tool("list_contacts", "List contacts"),
    ]
    p, _ = provider(FakeSession(tools))
    with pytest.raises(EnrichmentError, match="search_people"):  # listed, not called
        await p.enrich_contact(req(), allow_paid=True)
