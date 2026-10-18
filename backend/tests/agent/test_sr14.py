"""Regression tests for the SR14 review (docs/security/SR14-m3a.md)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import event, func, select

from app.agent import tools
from app.agent.schemas import SearchTextArgs
from app.db.models import Account, Company, Contact, Deal, Run
from app.flows.schemas import ClusterView, ColumnInfo, NodeResult
from app.services import themes
from tests.agent.conftest import INJECTION, call, dump, untrusted_paths
from tests.agent.test_tools import _flow

pytestmark = pytest.mark.integration


def _covered(path: str, listed: list[str]) -> bool:
    p = path.removeprefix("data.")
    while p.endswith("[]"):
        p = p[:-2]
    return p in listed or p.split(".")[-1].endswith("_untrusted")


def test_sr14_01_every_customer_string_is_listed_as_untrusted(db_session, demo):
    ws = demo.ws_id
    db_session.get(Contact, demo.contact_id).title = INJECTION
    db_session.get(Company, demo.company_id).name = INJECTION
    db_session.get(Account, demo.account_id).industry = INJECTION
    deal = db_session.scalars(select(Deal).where(Deal.account_id == demo.account_id)).first()
    if deal:
        deal.name = INJECTION
    flow = _flow(db_session, ws, name=INJECTION)
    db_session.flush()
    runs = {
        "search_companies": {"query": "a"},
        "get_company": {"company_id": demo.company_id},
        "get_account": {"account_id": demo.account_id},
        "list_deals": {},
        "list_flows": {},
        "run_flow": {"flow_id": flow.id},
        "workspace_overview": {},
    }
    seen = 0
    for name, kw in runs.items():
        out = dump(call(name, db_session, ws, **kw))
        for path in untrusted_paths(out, "IGNORE ALL PREVIOUS"):
            seen += 1
            assert _covered(path, out["untrusted_fields"]), (name, path)
    assert seen >= 5


def test_sr14_01_no_customer_string_is_a_json_key():
    r = NodeResult(
        node_id="n",
        status="ok",
        n_rows=1,
        columns=[ColumnInfo(name=INJECTION, dtype="text")],
        preview=[{INJECTION: "v"}],
        view=ClusterView(
            k=1, sizes=[1], centroids=[{INJECTION: 1.0}], metrics=[], dropped_missing=0
        ),
    )
    out = dump_node(r)
    assert len(out["preview_untrusted"]["columns_untrusted"]) == 1

    def keys(v):
        if isinstance(v, dict):
            for k, x in v.items():
                yield k
                yield from keys(x)
        elif isinstance(v, list):
            for x in v:
                yield from keys(x)

    assert not [k for k in keys(out) if "IGNORE" in k]
    assert out["preview_untrusted"]["rows_untrusted"] == [["v"]]
    assert out["view"]["centroids"][0]["features_untrusted"]


def dump_node(r, notes=None):
    import json

    return json.loads(tools._node_out(r, [] if notes is None else notes).model_dump_json())


def test_sr14_02_secret_looking_columns_are_blanked():
    names = ["value_enc", "Password", "API_KEY", "user_email", "Téléphone", "Mobile", "city"]
    r = NodeResult(
        node_id="n",
        status="ok",
        n_rows=1,
        columns=[ColumnInfo(name=n, dtype="text") for n in names],
        preview=[{n: "SECRET-" + n for n in names}],
    )
    notes: list[str] = []
    out = dump_node(r, notes)
    assert out["preview_untrusted"]["rows_untrusted"] == [[None] * 6 + ["SECRET-city"]]
    assert "SECRET-value_enc" not in str(out)
    assert notes and "value_enc" in notes[0] and "city" not in notes[0]


def test_sr14_03_columns_are_capped_and_size_guarded():
    names = [f"c{i}" for i in range(400)]
    r = NodeResult(
        node_id="n",
        status="ok",
        n_rows=60,
        columns=[ColumnInfo(name=n, dtype="text") for n in names],
        preview=[{n: "x" * 300 for n in names} for _ in range(60)],
    )
    notes: list[str] = []
    out = dump_node(r, notes)
    assert len(out["columns"]) == 60 and len(out["preview_untrusted"]["columns_untrusted"]) == 60
    assert any("340 columns dropped" in n for n in notes)

    from app.mcp_server import server

    payload = {
        "data": {"results": [{"columns": ["a"], "preview_untrusted": {
            "columns_untrusted": ["a"], "rows_untrusted": [["y" * 300]] * 5000}}]},
        "notes": [],
    }  # fmt: skip
    assert server._size(payload) > server.MAX_RESULT_BYTES
    small = server.guard_size(payload)
    assert server._size(small) <= server.MAX_RESULT_BYTES
    assert any("too large" in n for n in small["notes"])
    assert small["data"]["results"][0]["preview_untrusted"]["columns_untrusted"] == ["a"]
    from app.agent.errors import ToolError

    huge = {"data": {"s": "z" * 1_200_000}, "notes": []}
    with pytest.raises(ToolError, match="node_id"):
        server.guard_size(huge)


def test_sr14_04_scan_is_reused_within_a_minute(db_session, demo):
    def n_scans():
        return db_session.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.workspace_id == demo.ws_id, Run.kind == "stats_scan")
        )

    first = call("run_scan", db_session, demo.ws_id)
    assert n_scans() == 1 and not any("reused" in n for n in first.notes)
    second = call("run_scan", db_session, demo.ws_id)
    assert n_scans() == 1
    assert any(n.startswith("reused the scan from") for n in second.notes)
    assert second.data.scan_run_id == first.data.scan_run_id
    cg = call("compare_groups", db_session, demo.ws_id, dimension="lead_source", metric="win_rate")
    assert n_scans() == 1 and cg.data.scan_run_id == first.data.scan_run_id


def test_sr14_04_agent_call_rows_are_pruned(session_factory, demo, monkeypatch):
    from app.domain.enums import RunStatus
    from app.mcp_server import server

    monkeypatch.setattr(server, "AGENT_CALL_KEEP", 3)
    for i in range(6):
        server.record_call(
            session_factory,
            demo.ws_id,
            "t",
            {"i": i},
            RunStatus.SUCCEEDED,
            {"ok": True, "rows": 0},
            1,
        )
    with session_factory() as s:
        n = s.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.workspace_id == demo.ws_id, Run.kind == "agent_call")
        )
    assert n == 3


def test_sr14_06_account_notes_use_one_bounded_query(db_session, demo):
    seen: list[str] = []
    engine = db_session.get_bind()

    def spy(conn, cursor, statement, *a):
        if "FROM note" in statement:
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", spy)
    try:
        out = call("get_account", db_session, demo.ws_id, account_id=demo.account_id)
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    assert len(seen) == 1 and "LIMIT" in seen[0]
    assert any(n.kind == "note" for n in out.data.notes_and_comments)


def test_sr14_06_short_search_and_theme_cap(db_session, demo, monkeypatch):
    for q in ("e", " e ", "_ "):
        with pytest.raises(ValidationError):
            SearchTextArgs(query=q)
    themes.run_themes(db_session, demo.ws_id, k=3)
    monkeypatch.setattr(tools, "MAX_THEMES", 1)
    out = call("get_themes", db_session, demo.ws_id)
    assert len(out.data.themes) == 1 and any("only the first 1" in n for n in out.notes)
