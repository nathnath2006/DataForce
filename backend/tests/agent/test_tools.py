from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.agent.errors import ToolError
from app.agent.schemas import Envelope
from app.agent.tools import TOOLS
from app.db.models import Account, Company, Contact, Deal, Document, Run
from app.domain.enums import ProposalOrigin
from app.services import flows as flow_svc
from app.services import org_proposals, themes, workspaces
from tests.agent.conftest import EMAIL, MOBILE, call, dump, untrusted_paths

pytestmark = pytest.mark.integration

ALL_TOOLS = [
    "workspace_overview", "search_companies", "get_company", "get_account", "list_deals",
    "pipeline_summary", "compare_groups", "run_scan", "list_flows", "run_flow",
    "list_meetings", "get_meeting", "get_themes", "search_text",
]  # fmt: skip

GRAPH = {
    "version": 1,
    "nodes": [
        {
            "id": "d",
            "position": {"x": 0, "y": 0},
            "config": {"type": "dataset", "dataset": {"source": "crm", "table": "deals"}},
        },
        {
            "id": "s",
            "position": {"x": 1, "y": 0},
            "config": {"type": "sort", "keys": [{"column": "created_on"}], "limit": 5},
        },
    ],
    "edges": [{"id": "e1", "source": "d", "target": "s"}],
}


def _flow(db, ws_id, name="deals sorted"):
    from app.flows.schemas import FlowGraph

    return flow_svc.create_flow(db, ws_id, name, None, FlowGraph.model_validate(GRAPH))


def _args_for(name, demo, db):
    doc = db.scalars(select(Document).where(Document.workspace_id == demo.ws_id)).first()
    return {
        "search_companies": {"query": "a"},
        "get_company": {"company_id": demo.company_id},
        "get_account": {"account_id": demo.account_id},
        "compare_groups": {"dimension": "lead_source", "metric": "win_rate"},
        "run_flow": {"name": "deals sorted"},
        "get_meeting": {"document_id": doc.id},
        "search_text": {"query": "ee"},
    }.get(name, {})


def test_registry_is_complete():
    assert sorted(TOOLS) == sorted(ALL_TOOLS)
    for spec in TOOLS.values():
        assert spec.read_only and spec.description and spec.name == spec.fn.__name__
        assert spec.result_model is not None and spec.args_model is not None
    assert not TOOLS["workspace_overview"].writes_run and TOOLS["run_scan"].writes_run
    assert TOOLS["workspace_overview"].idempotent and not TOOLS["run_flow"].idempotent


@pytest.mark.parametrize("name", ALL_TOOLS)
def test_every_tool_returns_a_valid_envelope(name, db_session, demo):
    _flow(db_session, demo.ws_id)
    res = call(name, db_session, demo.ws_id, **_args_for(name, demo, db_session))
    assert isinstance(res, Envelope) and res.computed_by == "code"
    TOOLS[name].result_model.model_validate(dump(res))
    assert len(res.model_dump_json()) < 1_000_000


def test_overview_counts_match_sql(db_session, demo):
    d = dump(call("workspace_overview", db_session, demo.ws_id))["data"]
    ws = demo.ws_id

    def n(model, *cond):
        return db_session.scalar(
            select(func.count()).select_from(model).where(model.workspace_id == ws, *cond)
        )

    c = d["counts"]
    assert c["kind"] == "exact_count" and d["synthetic"] is True
    assert c["companies"] == n(Company) and c["accounts"] == n(Account)
    assert c["contacts"] == n(Contact) and c["meetings"] == n(Document)
    assert c["deals_won"] == n(Deal, Deal.stage == "closed_won")
    assert c["deals_lost"] == n(Deal, Deal.stage == "closed_lost")
    open_ = n(Deal, Deal.stage.in_(["prospecting", "qualification", "proposal", "negotiation"]))
    assert c["deals_open"] == open_
    assert sum(s["count"] for s in d["pipeline_by_stage"].values()) == n(Deal) == 60
    assert d["gates"]["min_n"] >= 1 and d["latest_scan_at"] is None


def test_pipeline_matches_overview_and_list_deals_total(db_session, demo):
    p = dump(call("pipeline_summary", db_session, demo.ws_id))["data"]
    assert p["n_deals"] == 60 and p["kind"] == "exact_count"
    deals = dump(call("list_deals", db_session, demo.ws_id, stage="closed_won"))["data"]
    assert deals["page"]["total"] == p["n_won"]
    assert all(r["stage"] == "closed_won" for r in deals["deals"])


def test_search_and_get_company(db_session, demo):
    hits = dump(call("search_companies", db_session, demo.ws_id, query=demo.company_name[:6]))
    assert any(h["id"] == str(demo.company_id) for h in hits["data"]["companies"])
    by_name = call("get_company", db_session, demo.ws_id, name=demo.company_name)
    by_id = call("get_company", db_session, demo.ws_id, company_id=demo.company_id)
    assert by_name.data.id == by_id.data.id == demo.company_id
    assert by_id.data.n_accounts == len(by_id.data.accounts) >= 1
    assert len(by_id.data.recent_activity) <= 20
    with pytest.raises(ValidationError):
        call("get_company", db_session, demo.ws_id)  # neither id nor name


def test_get_account_separates_confirmed_and_suggested(db_session, demo):
    before = call("get_account", db_session, demo.ws_id, account_id=demo.account_id).data
    assert before.org_suggestions_not_verified == []
    org_proposals.propose(db_session, demo.ws_id, demo.account_id, [ProposalOrigin.RULE])
    after = call("get_account", db_session, demo.ws_id, name=demo.account_name).data
    confirmed = {(c["contact_id"], c["manager_id"]) for c in after.org_chart_confirmed}
    assert confirmed == {(c.id, c.manager_id) for c in before.contacts if c.manager_id}
    for s in after.org_suggestions_not_verified:
        assert s.verified is False and s.status in ("proposed", "ambiguous")
        assert (s.contact_id, s.manager_id) not in confirmed
    assert all(
        c.title_seniority is None or isinstance(c.title_seniority, str) for c in after.contacts
    )


def test_compare_groups_matches_run_scan(db_session, demo):
    first = call(
        "compare_groups", db_session, demo.ws_id, dimension="lead_source", metric="win_rate"
    )
    assert first.data.scan_was_run_now is True
    assert (
        db_session.scalar(select(func.count()).select_from(Run).where(Run.kind == "stats_scan"))
        == 1
    )
    scan = call("run_scan", db_session, demo.ws_id).data
    for dim, metric in (
        ("lead_source", "win_rate"),
        ("segment", "cycle_days"),
        ("owner", "deal_amount"),
    ):
        cg = call("compare_groups", db_session, demo.ws_id, dimension=dim, metric=metric)
        assert cg.data.scan_was_run_now is False and cg.data.scan_run_id == scan.scan_run_id
        assert cg.data.n_verified + cg.data.n_not_verified == len(cg.data.findings)
        for f in cg.data.findings:
            assert f.status in ("verified", "not_verified")
            assert (f.status == "verified") == (f.reasons == [])
    all_f = [
        f
        for d in ("lead_source", "segment", "industry", "region", "owner", "amount_band")
        for m in ("win_rate", "cycle_days", "deal_amount")
        for f in call("compare_groups", db_session, demo.ws_id, dimension=d, metric=m).data.findings
    ]
    assert sorted(
        (f.dimension, f.group, f.metric) for f in all_f if f.status == "verified"
    ) == sorted((f.dimension, f.group, f.metric) for f in scan.verified_findings)
    assert scan.n_not_verified == sum(f.status == "not_verified" for f in all_f)
    assert all(f.status == "verified" for f in scan.verified_findings)


def test_run_scan_records_a_run(db_session, demo):
    call("run_scan", db_session, demo.ws_id)
    runs = db_session.scalars(select(Run).where(Run.kind == "stats_scan")).all()
    assert len(runs) == 1 and runs[0].status == "succeeded"


def test_flows_list_and_run(db_session, demo):
    f = _flow(db_session, demo.ws_id)
    listed = call("list_flows", db_session, demo.ws_id).data.flows
    assert [(x.id, [b["type"] for b in x.blocks]) for x in listed] == [(f.id, ["dataset", "sort"])]
    res = call("run_flow", db_session, demo.ws_id, flow_id=f.id)
    assert [r.node_id for r in res.data.results] == ["s"]  # the sink only
    r = res.data.results[0]
    assert r.status == "ok" and r.n_rows == 5 and len(r.preview_untrusted["rows_untrusted"]) == 5
    one = call("run_flow", db_session, demo.ws_id, name="deals sorted", node_id="d").data.results
    assert [x.node_id for x in one] == ["d"] and one[0].n_rows == 60
    assert len(one[0].preview_untrusted["rows_untrusted"]) == 50  # preview cap
    run = db_session.scalars(select(Run).where(Run.kind == "flow_run")).first()
    assert run is not None and "Acme" not in json.dumps(run.result)
    with pytest.raises(ToolError, match="node_id"):
        call("run_flow", db_session, demo.ws_id, flow_id=f.id, node_id="nope")


def test_meetings_and_themes(db_session, demo):
    ms = call("list_meetings", db_session, demo.ws_id, limit=5).data
    assert ms.page.total == db_session.scalar(select(func.count()).select_from(Document)) > 0
    assert ms.page.returned == len(ms.meetings) <= 5
    m = ms.meetings[0]
    full = call("get_meeting", db_session, demo.ws_id, document_id=m.id).data
    assert full.meeting.id == m.id and full.n_turns >= 1 and full.turns[0].char_start >= 0
    by_account = call("list_meetings", db_session, demo.ws_id, account_id=m.account_id).data
    assert all(x.account_id == m.account_id for x in by_account.meetings)
    empty = call("get_themes", db_session, demo.ws_id).data
    assert empty.themes == [] and empty.run_id is None
    themes.run_themes(db_session, demo.ws_id, k=3)
    got = call("get_themes", db_session, demo.ws_id).data
    assert got.run_id is not None and got.themes
    assert {t.origin for t in got.themes} <= {"known", "discovered"}
    assert all(len(t.excerpts) <= 3 for t in got.themes)
    assert any(
        x.themes_untrusted for x in call("list_meetings", db_session, demo.ws_id).data.meetings
    )


def test_get_meeting_pages_the_text(db_session, demo):
    doc = max(db_session.scalars(select(Document).where(Document.workspace_id == demo.ws_id)),
              key=lambda d: d.n_chars)  # fmt: skip
    a = call("get_meeting", db_session, demo.ws_id, document_id=doc.id, max_chars=100).data
    assert len(a.text_untrusted) <= 100 and a.next_offset == len(a.text_untrusted) < doc.n_chars
    b = call("get_meeting", db_session, demo.ws_id, document_id=doc.id, offset=a.next_offset,
             max_chars=100).data  # fmt: skip
    assert (a.text_untrusted + b.text_untrusted)[:200] == doc.text[
        : len(a.text_untrusted) + len(b.text_untrusted)
    ][:200]
    tail = call("get_meeting", db_session, demo.ws_id, document_id=doc.id, offset=doc.n_chars).data
    assert tail.text_untrusted == "" and tail.next_offset is None
    with pytest.raises(ValidationError):
        call("get_meeting", db_session, demo.ws_id, document_id=doc.id, max_chars=20_001)


def test_search_text_finds_notes_comments_meetings(db_session, demo):
    r = call("search_text", db_session, demo.ws_id, query="call went well").data
    assert r.method == "substring" and r.total_by_source["notes"] >= 1
    assert any(h.source == "notes" and "Call went well" in h.excerpt_untrusted for h in r.hits)
    # a LIKE wildcard is a literal
    assert call("search_text", db_session, demo.ws_id, query="%%").data.total_by_source == {
        "notes": 0, "comments": 0, "meetings": 0,
    }  # fmt: skip
    only = call(
        "search_text", db_session, demo.ws_id, query="ee", sources=["meetings"], limit=3
    ).data
    assert len(only.hits) <= 3 and set(only.total_by_source) == {"meetings"}
    assert all(len(h.excerpt_untrusted) <= 320 for h in only.hits)
    with pytest.raises(ValidationError):
        call("search_text", db_session, demo.ws_id, query="x" * 201)


def test_injection_stays_inside_untrusted_fields(db_session, demo):
    outs = {
        "get_account": call("get_account", db_session, demo.ws_id, account_id=demo.account_id),
        "get_company": call("get_company", db_session, demo.ws_id, company_id=demo.company_id),
        "search_text": call("search_text", db_session, demo.ws_id, query="ignore all previous"),
    }
    seen = 0
    for name, res in outs.items():
        paths = untrusted_paths(dump(res), "IGNORE ALL PREVIOUS")
        seen += len(paths)
        assert all(p.split(".")[-1].endswith("_untrusted") for p in paths), (name, paths)
        assert "</source>" not in res.model_dump_json()  # tag look-alikes are neutralised
        listed = set(res.untrusted_fields)
        assert all(p.removeprefix("data.") in listed for p in paths), (paths, listed)
    assert seen >= 2


def test_untrusted_text_is_sanitised_and_capped(db_session, demo):
    from app.services import notes

    notes.add_note(db_session, demo.ws_id, demo.contact_id, None, "x‮​" + "y" * 5000)
    feed = call(
        "get_account", db_session, demo.ws_id, account_id=demo.account_id
    ).data.notes_and_comments
    body = next(n.body_untrusted for n in feed if n.body_untrusted.startswith("xy"))
    assert len(body) == 2000 and "‮" not in body and "​" not in body


@pytest.mark.parametrize("name", ALL_TOOLS)
def test_no_channel_value_or_secret_in_any_tool(name, db_session, demo):
    from app.demo.generator import generate  # noqa: F401

    _flow(db_session, demo.ws_id)
    res = call(name, db_session, demo.ws_id, **_args_for(name, demo, db_session))
    text = res.model_dump_json()
    for secret in (EMAIL, MOBILE, "value_enc", "password", "api_key", "access_token"):
        assert secret not in text
    assert "n_channels" not in text


def test_no_channel_value_when_a_flow_reads_contacts(db_session, demo):
    from app.flows.schemas import FlowGraph

    graph = {
        "version": 1,
        "nodes": [{
            "id": "c", "position": {"x": 0, "y": 0},
            "config": {"type": "dataset", "dataset": {"source": "crm", "table": "contacts"}},
        }],
        "edges": [],
    }  # fmt: skip
    flow_svc.create_flow(db_session, demo.ws_id, "contacts", None, FlowGraph.model_validate(graph))
    text = call("run_flow", db_session, demo.ws_id, name="contacts").model_dump_json()
    assert EMAIL not in text and MOBILE not in text and '"n_rows":' in text


def test_caps_and_paging(db_session, demo):
    for bad in (0, 501):
        with pytest.raises(ValidationError):
            call("list_deals", db_session, demo.ws_id, limit=bad)
    with pytest.raises(ValidationError):
        call("list_deals", db_session, demo.ws_id, offset=-1)
    default = call("list_deals", db_session, demo.ws_id).data
    assert default.page.limit == 50 and len(default.deals) == 50 and default.page.total == 60
    p1 = call("list_deals", db_session, demo.ws_id, limit=25).data.deals
    p2 = call("list_deals", db_session, demo.ws_id, limit=25, offset=25).data.deals
    p3 = call("list_deals", db_session, demo.ws_id, limit=25, offset=50).data
    ids = [d.id for d in p1 + p2 + p3.deals]
    assert len(ids) == len(set(ids)) == 60 and p3.page.returned == 10
    assert (
        len(call("search_companies", db_session, demo.ws_id, query="a", limit=2).data.companies)
        <= 2
    )
    assert call("list_meetings", db_session, demo.ws_id, limit=1).data.page.returned == 1


def test_list_deals_filters(db_session, demo):
    some = call("list_deals", db_session, demo.ws_id, limit=500).data.deals
    d = some[0]
    by_acc = call("list_deals", db_session, demo.ws_id, account_id=d.account_id).data
    assert by_acc.page.total == sum(x.account_id == d.account_id for x in some)
    ranged = call(
        "list_deals", db_session, demo.ws_id, created_from=d.created_on, created_to=d.created_on
    )
    assert ranged.data.page.total == sum(x.created_on == d.created_on for x in some)
    owner = next(x.owner for x in some if x.owner)
    assert call("list_deals", db_session, demo.ws_id, owner=owner).data.page.total == sum(
        x.owner == owner for x in some
    )
    with pytest.raises(ToolError, match="owner"):
        call("list_deals", db_session, demo.ws_id, owner="Nobody At All")
    with pytest.raises(ToolError, match="created_from"):
        call(
            "list_deals", db_session, demo.ws_id, created_from="2025-02-01", created_to="2025-01-01"
        )
    with pytest.raises(ValidationError):
        call("list_deals", db_session, demo.ws_id, stage="bogus")


def test_unknown_ids_raise_clean_tool_errors(db_session, demo):
    ghost = uuid.uuid4()
    cases = [
        ("get_company", {"company_id": ghost}),
        ("get_company", {"name": "No Such Company"}),
        ("get_account", {"account_id": ghost}),
        ("get_account", {"name": "No Such Account"}),
        ("list_deals", {"account_id": ghost}),
        ("run_flow", {"flow_id": ghost}),
        ("run_flow", {"name": "nope"}),
        ("list_meetings", {"account_id": ghost}),
        ("list_meetings", {"company_id": ghost}),
        ("get_meeting", {"document_id": ghost}),
    ]
    for name, kw in cases:
        with pytest.raises(ToolError) as exc:
            call(name, db_session, demo.ws_id, **kw)
        msg = str(exc.value)
        assert "not found" in msg and "SELECT" not in msg and str(ghost) not in msg


def test_workspace_isolation(db_session, demo):
    other = workspaces.create_workspace(db_session, "other-ws", "Other").id
    doc = db_session.scalars(select(Document).where(Document.workspace_id == demo.ws_id)).first()
    flow = _flow(db_session, demo.ws_id)
    for name, kw in [
        ("get_account", {"account_id": demo.account_id}),
        ("get_account", {"name": demo.account_name}),
        ("get_company", {"company_id": demo.company_id}),
        ("get_company", {"name": demo.company_name}),
        ("list_deals", {"account_id": demo.account_id}),
        ("get_meeting", {"document_id": doc.id}),
        ("run_flow", {"flow_id": flow.id}),
        ("list_meetings", {"account_id": demo.account_id}),
    ]:
        with pytest.raises(ToolError):
            call(name, db_session, other, **kw)
    ov = call("workspace_overview", db_session, other).data
    assert ov.counts.accounts == 0 and ov.synthetic is False
    assert call("list_flows", db_session, other).data.flows == []
    assert call("search_text", db_session, other, query="ee").data.hits == []
    assert call("search_companies", db_session, other, query="a").data.page.total == 0
    assert call("list_deals", db_session, other).data.page.total == 0
