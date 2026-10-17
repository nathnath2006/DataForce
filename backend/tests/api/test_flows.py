from __future__ import annotations

import pytest

from app.api.routes.flows import get_loader_session_factory
from app.flows.schemas import NodeResult
from app.services import flows as flow_service

pytestmark = pytest.mark.integration

GRAPH = {
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
                "by": ["stage"],
                "aggregations": [{"fn": "count", "as": "n"}],
            },
        },
    ],
    "edges": [{"id": "e", "source": "d", "target": "g"}],
}


@pytest.fixture
def ws(client, app, session_factory):
    app.dependency_overrides[get_loader_session_factory] = lambda: session_factory
    client.post("/api/workspaces", json={"slug": "f1", "name": "F1"})
    client.post("/api/workspaces", json={"slug": "f2", "name": "F2"})
    return "/api/w/f1"


def test_crud_and_alias_roundtrip(client, ws):
    r = client.post(f"{ws}/flows", json={"name": "A", "graph": GRAPH})
    assert r.status_code == 201
    fid = r.json()["id"]
    assert r.json()["graph"]["nodes"][1]["config"]["aggregations"][0]["as"] == "n"
    assert client.post(f"{ws}/flows", json={"name": "E"}).json()["graph"]["nodes"] == []
    summ = client.get(f"{ws}/flows").json()
    assert {s["name"]: s["n_nodes"] for s in summ} == {"A": 2, "E": 0}
    u = client.put(f"{ws}/flows/{fid}", json={"name": "B"})
    assert u.json()["name"] == "B" and len(u.json()["graph"]["nodes"]) == 2
    assert client.get("/api/w/f2/flows").json() == []
    assert client.get(f"/api/w/f2/flows/{fid}").status_code == 404
    assert client.delete(f"{ws}/flows/{fid}").status_code == 204
    assert client.get(f"{ws}/flows/{fid}").status_code == 404


def test_invalid_graph_refused(client, ws):
    bad = {**GRAPH, "edges": GRAPH["edges"] + [{"id": "e2", "source": "g", "target": "d"}]}
    assert client.post(f"{ws}/flows", json={"name": "x", "graph": bad}).status_code == 422
    assert client.post(f"{ws}/flows", json={"name": "x", "bogus": 1}).status_code == 422


def test_catalog(client, ws):
    c = client.get(f"{ws}/flows/catalog").json()
    assert c["blocks"]["join"] == {"inputs": ["left", "right"], "outputs": ["out"]}
    assert [x["name"] for x in c["crm_tables"]["contacts"]][:2] == ["contact_id", "full_name"]


def test_run_records_summary_only(client, ws, monkeypatch, session_factory):
    seen = {}

    def fake(graph, loader, gates, limits, target):
        seen["rows"] = len(loader.load(graph.nodes[0].config.dataset, 10))
        return {
            "d": NodeResult(node_id="d", status="ok", n_rows=0, preview=[{"secret": "x"}]),
            "g": NodeResult(node_id="g", status="error", error="boom"),
        }

    monkeypatch.setattr(flow_service, "_engine_run", fake)
    acc = client.post(f"{ws}/accounts", json={"name": "Acme"}).json()
    client.post(
        f"{ws}/deals",
        json={
            "account_id": acc["id"],
            "name": "D",
            "stage": "proposal",
            "created_on": "2025-01-01",
        },
    )
    r = client.post(f"{ws}/flows/run", json={"graph": GRAPH})
    assert r.status_code == 200, r.text
    assert seen["rows"] == 1 and r.json()["results"]["g"]["error"] == "boom"
    from sqlalchemy import select

    from app.db.models import Run

    run = session_factory().scalar(select(Run).where(Run.kind == "flow_run"))
    assert run.status == "partial" and "secret" not in str(run.result)
    assert r.json()["run_id"]
    assert client.post(f"{ws}/flows/run", json={"graph": GRAPH, "target": "zz"}).status_code == 422


def test_run_timeout_is_504(client, ws, monkeypatch, api_settings):
    import time

    monkeypatch.setattr(flow_service, "_engine_run", lambda *a: time.sleep(1) or {})
    monkeypatch.setattr(
        flow_service,
        "run_in_thread",
        lambda fn, t: (
            flow_service.RunTimeout and (_ for _ in ()).throw(flow_service.RunTimeout("t"))
        ),
    )
    r = client.post(f"{ws}/flows/run", json={"graph": GRAPH})
    assert r.status_code == 504 and r.json()["error"]["code"] == "timeout"


def test_run_in_thread_timeout():
    import time

    with pytest.raises(flow_service.RunTimeout):
        flow_service.run_in_thread(lambda: time.sleep(1) or {}, 0.05)
