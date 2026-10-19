from __future__ import annotations

import time
from datetime import date

import pytest
from sqlalchemy import select

from app.api.routes.flows import get_loader_session_factory
from app.db.models import Account, Deal, Workspace
from app.services import flows as flow_service
from app.viz import source as viz_source

pytestmark = pytest.mark.integration

# smb: 10 won + 40 lost (amount 1000); enterprise: 40 won + 10 lost (amount 5000); 5 open smb.
PLAN = [
    ("smb", "closed_won", 10, 1000),
    ("smb", "closed_lost", 40, 1000),
    ("enterprise", "closed_won", 40, 5000),
    ("enterprise", "closed_lost", 10, 5000),
    ("smb", "proposal", 5, 1000),
]
CRM = {"kind": "crm", "table": "deals"}


@pytest.fixture(autouse=True)
def _fresh_slots():
    flow_service._slots = None
    yield
    flow_service._slots = None


def _seed(session_factory, slug: str) -> None:
    with session_factory() as s:
        ws = s.scalar(select(Workspace).where(Workspace.slug == slug))
        accs = {}
        for seg in ("smb", "enterprise"):
            a = Account(workspace_id=ws.id, name=f"A-{seg}", segment=seg)
            s.add(a)
            accs[seg] = a
        s.flush()
        i = 0
        for seg, stage, n, amount in PLAN:
            for _ in range(n):
                i += 1
                closed = stage.startswith("closed")
                s.add(
                    Deal(
                        workspace_id=ws.id,
                        account_id=accs[seg].id,
                        name=f"D{i}",
                        stage=stage,
                        amount_eur=amount,
                        created_on=date(2025, 1, 1),
                        closed_on=date(2025, 2, 1) if closed else None,
                    )
                )
        s.commit()


@pytest.fixture
def ws(client, app, session_factory):
    app.dependency_overrides[get_loader_session_factory] = lambda: session_factory
    client.post("/api/workspaces", json={"slug": "v1", "name": "V1"})
    client.post("/api/workspaces", json={"slug": "v2", "name": "V2"})
    _seed(session_factory, "v1")
    return "/api/w/v1"


def q(client, ws, **body):
    body.setdefault("source", CRM)
    return client.post(f"{ws}/viz/query", json=body)


def test_exact_aggregates(client, ws):
    r = q(
        client,
        ws,
        dimensions=["segment"],
        measures=[
            {"column": "*", "agg": "count"},
            {"column": "amount_eur", "agg": "sum"},
            {"column": "amount_eur", "agg": "mean"},
            {"column": "amount_eur", "agg": "min"},
            {"column": "stage", "agg": "count_distinct"},
        ],
        sort=[{"by": "segment"}],
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert [c["name"] for c in b["columns"]] == [
        "segment",
        "count",
        "sum(amount_eur)",
        "mean(amount_eur)",
        "min(amount_eur)",
        "count_distinct(stage)",
    ]
    assert b["rows"] == [
        ["enterprise", 50, 250000.0, 5000.0, 5000.0, 2],
        ["smb", 55, 55000.0, 1000.0, 1000.0, 3],
    ]
    assert b["n_source_rows"] == 105 and b["truncated_source"] is False


def test_no_dimension_median_and_default_sort(client, ws):
    b = q(client, ws, measures=[{"column": "amount_eur", "agg": "median"}]).json()
    assert b["rows"] == [[1000.0]]
    b = q(client, ws, dimensions=["stage"], measures=[{"column": "*", "agg": "count"}]).json()
    assert b["rows"][0] == ["closed_lost", 50] and b["n_groups"] == 3


def test_filters(client, ws):
    base = {"measures": [{"column": "*", "agg": "count"}]}

    def n(*filters):
        return q(client, ws, filters=list(filters), **base).json()["rows"][0][0]

    assert n({"column": "segment", "op": "eq", "value": "smb"}) == 55
    assert n({"column": "segment", "op": "ne", "value": "smb"}) == 50
    assert n({"column": "amount_eur", "op": "gt", "value": 1000}) == 50
    assert n({"column": "stage", "op": "in", "value": ["proposal", "closed_won"]}) == 55
    assert n({"column": "stage", "op": "contains", "value": "CLOSED"}) == 100
    assert n({"column": "is_won", "op": "is_null"}) == 5
    assert n({"column": "is_won", "op": "eq", "value": True}) == 50
    assert n({"column": "created_on", "op": "ge", "value": "2025-01-01"}) == 105
    assert n({"column": "closed_on", "op": "not_null"}) == 100
    assert (
        n(
            {"column": "segment", "op": "eq", "value": "smb"},
            {"column": "stage", "op": "eq", "value": "closed_won"},
        )
        == 10
    )


def test_invalid_requests_rejected(client, ws):
    m = [{"column": "*", "agg": "count"}]
    assert q(client, ws, dimensions=["nope"], measures=m).status_code == 422
    assert q(client, ws, dimensions=["__import__('os')"], measures=m).status_code == 422
    assert q(client, ws, measures=[{"column": "nope", "agg": "sum"}]).status_code == 422
    assert q(client, ws, measures=[{"column": "stage", "agg": "sum"}]).status_code == 422
    assert q(client, ws, measures=[{"column": "*", "agg": "sum"}]).status_code == 422
    assert (
        q(client, ws, measures=m, filters=[{"column": "x", "op": "eq", "value": 1}]).status_code
        == 422
    )
    assert (
        q(
            client, ws, measures=m, filters=[{"column": "amount_eur", "op": "gt", "value": "abc"}]
        ).status_code
        == 422
    )
    assert q(client, ws, dimensions=["segment"], measures=m, sort=[{"by": "zz"}]).status_code == 422
    assert q(client, ws, measures=m, limit=5001).status_code == 422
    assert q(client, ws, measures=m, limit=0).status_code == 422
    assert q(client, ws, measures=m, source={"kind": "crm", "table": "users"}).status_code == 422


def test_limit_truncates_groups(client, ws):
    b = q(
        client,
        ws,
        dimensions=["deal_name"],
        measures=[{"column": "*", "agg": "count"}],
        limit=7,
    ).json()
    assert len(b["rows"]) == 7 and b["n_groups"] == 105
    assert any("first 7 of 105" in n for n in b["notes"])


def test_workspace_isolation_crm(client, ws):
    b = client.post(
        "/api/w/v2/viz/query",
        json={"source": CRM, "measures": [{"column": "*", "agg": "count"}]},
    ).json()
    assert b["rows"] == [[0]]
    assert client.post("/api/w/nope/viz/query", json={"source": CRM}).status_code == 404


FLOW = {
    "version": 1,
    "nodes": [
        {
            "id": "d",
            "position": {"x": 0, "y": 0},
            "config": {"type": "dataset", "dataset": {"source": "crm", "table": "deals"}},
        },
        {
            "id": "g",
            "position": {"x": 1, "y": 0},
            "config": {
                "type": "group",
                "by": ["segment"],
                "aggregations": [{"fn": "count", "as": "n"}],
            },
        },
    ],
    "edges": [{"id": "e", "source": "d", "target": "g"}],
}


def test_flow_source_and_isolation(client, ws):
    fid = client.post(f"{ws}/flows", json={"name": "F", "graph": FLOW}).json()["id"]
    src = {"kind": "flow", "flow_id": fid, "node_id": "g"}
    b = q(
        client,
        ws,
        source=src,
        dimensions=["segment"],
        measures=[{"column": "n", "agg": "sum"}],
        sort=[{"by": "segment"}],
    ).json()
    assert b["rows"] == [["enterprise", 50.0], ["smb", 55.0]] or b["rows"] == [
        ["enterprise", 50],
        ["smb", 55],
    ]
    # another workspace cannot read it
    other = client.post(
        "/api/w/v2/viz/query", json={"source": src, "measures": [{"column": "*", "agg": "count"}]}
    )
    assert other.status_code == 404
    # unknown node, unknown flow
    bad = {**src, "node_id": "zz"}
    assert q(client, ws, source=bad, measures=[{"column": "*", "agg": "count"}]).status_code == 422
    unk = {**src, "flow_id": "00000000-0000-0000-0000-000000000000"}
    assert q(client, ws, source=unk, measures=[{"column": "*", "agg": "count"}]).status_code == 404


def test_truncated_source_is_reported(client, ws, monkeypatch):
    import app.viz.source as vs

    real = vs.DbSourceLoader.load

    def capped(self, source, max_rows):
        return real(self, source, 100)

    monkeypatch.setattr(vs.DbSourceLoader, "load", capped)
    b = q(client, ws, measures=[{"column": "*", "agg": "count"}]).json()
    assert b["truncated_source"] is True and b["rows"] == [[100]]
    assert any("first 100 rows" in n for n in b["notes"])


def test_time_budget(client, ws, monkeypatch):
    monkeypatch.setattr(viz_source, "TIME_BUDGET_S", 0.1)
    real = viz_source.DbSourceLoader.load

    def slow(self, source, max_rows):
        time.sleep(0.5)
        return real(self, source, max_rows)

    monkeypatch.setattr(viz_source.DbSourceLoader, "load", slow)
    r = q(client, ws, measures=[{"column": "*", "agg": "count"}])
    assert r.status_code == 422 and "did not finish" in r.json()["error"]["message"]


def test_fields(client, ws):
    b = client.post(f"{ws}/viz/fields", json={"source": CRM}).json()
    kinds = {c["name"]: c["dtype"] for c in b["columns"]}
    assert kinds["segment"] == "text" and kinds["amount_eur"] == "number"
    assert b["n_source_rows"] == 105


def test_explain_verified_and_not_verified(client, ws):
    body = {
        "source": CRM,
        "measure": {"column": "is_won", "kind": "rate", "success_value": True},
        "attributes": ["segment", "stage"],
    }
    b = client.post(f"{ws}/viz/explain", json=body).json()
    ver = {(f["attribute"], f["group"]): f for f in b["verified"]}
    assert ("segment", "enterprise") in ver and ("segment", "smb") in ver
    ent = ver[("segment", "enterprise")]
    assert (
        ent["n"] == 50
        and ent["value"] == pytest.approx(0.8, abs=0.1)
        and ent["direction"] == "higher"
    )
    assert ver[("segment", "smb")]["direction"] == "lower"
    # stage groups predict the outcome perfectly but have no losing side: engine reasons them away
    nv = [f for f in b["not_verified"] if f["attribute"] == "stage"]
    assert nv and all(f["reasons"] and f["status"] == "not_verified" for f in nv)
    assert b["method"].startswith("wilson")


def test_explain_median_filters_and_errors(client, ws):
    body = {
        "source": CRM,
        "measure": {"column": "amount_eur", "kind": "median"},
        "attributes": ["segment"],
        "filters": [{"column": "is_closed", "op": "eq", "value": True}],
    }
    b = client.post(f"{ws}/viz/explain", json=body).json()
    assert b["n_rows"] == 100
    assert {f["group"] for f in b["verified"] + b["not_verified"]} == {"smb", "enterprise"}
    body["attributes"] = ["nope"]
    assert client.post(f"{ws}/viz/explain", json=body).status_code == 422
    body["attributes"] = list("abcdef")
    assert client.post(f"{ws}/viz/explain", json=body).status_code == 422
    body["attributes"] = ["amount_eur"]  # a numeric measure can't be its own attribute
    r = client.post(f"{ws}/viz/explain", json=body).json()
    assert r["verified"] == [] and any("measure itself" in n for n in r["notes"])


def test_filter_bounds(client, ws):
    m = [{"column": "*", "agg": "count"}]
    many = [{"column": "segment", "op": "in", "value": list(range(501))}]
    assert q(client, ws, measures=m, filters=many).status_code == 422
    long = [{"column": "segment", "op": "eq", "value": "x" * 1001}]
    assert q(client, ws, measures=m, filters=long).status_code == 422


def test_crm_load_takes_a_concurrency_slot(client, ws, monkeypatch):
    import threading

    slot = threading.BoundedSemaphore(1)
    monkeypatch.setattr(viz_source.flows, "_semaphore", lambda size: slot)
    monkeypatch.setattr(viz_source, "SLOT_WAIT_S", 0.05)
    slot.acquire()
    r = q(client, ws, measures=[{"column": "*", "agg": "count"}])
    assert r.status_code == 422 and "still running" in r.json()["error"]["message"]
    slot.release()
    assert q(client, ws, measures=[{"column": "*", "agg": "count"}]).status_code == 200
    assert slot.acquire(blocking=False)  # released after the load
    # a tile waits for a slot freed while it waits (a canvas sends its queries at once)
    monkeypatch.setattr(viz_source, "SLOT_WAIT_S", 5.0)
    threading.Timer(0.2, slot.release).start()
    assert q(client, ws, measures=[{"column": "*", "agg": "count"}]).status_code == 200
