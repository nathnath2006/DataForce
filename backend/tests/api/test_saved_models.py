from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.api.routes.flows import get_loader_session_factory
from app.db.models import Account, Deal, Workspace
from app.services import flows as flow_service

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _fresh_slots():
    flow_service._slots = None
    yield
    flow_service._slots = None


def _seed(session_factory, slug: str) -> None:
    with session_factory() as s:
        ws = s.scalar(select(Workspace).where(Workspace.slug == slug))
        acc = Account(workspace_id=ws.id, name="A", segment="smb")
        s.add(acc)
        s.flush()
        for i in range(160):
            days = 10 + (i * 7) % 90
            s.add(
                Deal(
                    workspace_id=ws.id,
                    account_id=acc.id,
                    name=f"D{i}",
                    stage="closed_won" if i % 3 else "closed_lost",
                    amount_eur=1000 + 50 * days + (i % 5) * 10,
                    created_on=date(2025, 1, 1),
                    closed_on=date(2025, 1, 1) + timedelta(days=days),
                )
            )
        s.commit()


def node(nid, cfg):
    return {"id": nid, "position": {"x": 0, "y": 0}, "config": cfg}


def model_flow(kernel="linear", kind="svr"):
    return {
        "version": 1,
        "nodes": [
            node("d", {"type": "dataset", "dataset": {"source": "crm", "table": "deals"}}),
            node("s", {"type": "split", "test_fraction": 0.3}),
            node(
                "m",
                {
                    "type": "model",
                    "kind": kind,
                    "kernel": kernel,
                    "target": "amount_eur",
                    "features": ["cycle_days"],
                },
            ),
        ],
        "edges": [
            {"id": "e1", "source": "d", "target": "s"},
            {
                "id": "e2",
                "source": "s",
                "source_port": "train",
                "target": "m",
                "target_port": "train",
            },
            {
                "id": "e3",
                "source": "s",
                "source_port": "test",
                "target": "m",
                "target_port": "test",
            },
        ],
    }


@pytest.fixture
def ws(client, app, session_factory):
    app.dependency_overrides[get_loader_session_factory] = lambda: session_factory
    client.post("/api/workspaces", json={"slug": "m1", "name": "M1"})
    client.post("/api/workspaces", json={"slug": "m2", "name": "M2"})
    _seed(session_factory, "m1")
    return "/api/w/m1"


def make_flow(client, ws, graph):
    return client.post(f"{ws}/flows", json={"name": "F", "graph": graph}).json()["id"]


def test_save_list_get_rename_delete_and_isolation(client, ws):
    fid = make_flow(client, ws, model_flow())
    r = client.post(f"{ws}/models", json={"flow_id": fid, "node_id": "m", "name": " My model "})
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["name"] == "My model" and m["kind"] == "svr" and m["features"] == ["cycle_days"]
    assert m["flow_id"] == fid and m["node_id"] == "m"
    names = [x["name"] for x in m["metrics"]["metrics"]]
    assert "r2" in names and m["metrics"]["metrics"][0]["baseline"] == 0.0
    # the status is the block's own verdict
    run = client.post(f"{ws}/flows/run", json={"graph": model_flow(), "target": "m"}).json()
    assert m["status"] == run["results"]["m"]["view"]["status"]
    mid = m["id"]
    assert [x["id"] for x in client.get(f"{ws}/models").json()] == [mid]
    assert client.get(f"{ws}/models/{mid}").json()["name"] == "My model"
    assert client.patch(f"{ws}/models/{mid}", json={"name": "Renamed"}).json()["name"] == "Renamed"
    assert client.patch(f"{ws}/models/{mid}", json={"name": " "}).status_code == 422
    # another workspace sees nothing
    assert client.get("/api/w/m2/models").json() == []
    assert client.get(f"/api/w/m2/models/{mid}").status_code == 404
    assert client.patch(f"/api/w/m2/models/{mid}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/w/m2/models/{mid}").status_code == 404
    other = client.post("/api/w/m2/models", json={"flow_id": fid, "node_id": "m", "name": "x"})
    assert other.status_code == 404
    assert client.delete(f"{ws}/models/{mid}").status_code == 204
    assert client.get(f"{ws}/models/{mid}").status_code == 404


def test_client_cannot_send_parameters(client, ws):
    fid = make_flow(client, ws, model_flow())
    r = client.post(
        f"{ws}/models",
        json={
            "flow_id": fid,
            "node_id": "m",
            "name": "x",
            "params": {"coef": [1]},
            "status": "verified",
        },
    )
    assert r.status_code == 422


def test_refusals(client, ws, monkeypatch):
    fid = make_flow(client, ws, model_flow())
    body = {"flow_id": fid, "name": "x"}
    not_model = client.post(f"{ws}/models", json={**body, "node_id": "d"})
    assert not_model.status_code == 422 and "model" in not_model.json()["error"]["message"]
    assert client.post(f"{ws}/models", json={**body, "node_id": "zz"}).status_code == 422
    bad = model_flow()
    bad["nodes"][2]["config"]["features"] = ["no_such_column"]
    bid = make_flow(client, ws, bad)
    failed = client.post(f"{ws}/models", json={"flow_id": bid, "node_id": "m", "name": "x"})
    assert failed.status_code == 422 and "nothing was saved" in failed.json()["error"]["message"]
    import app.flows.blocks.model as model_block

    monkeypatch.setattr(model_block, "MAX_EXPORTED_SV", 1)
    rbf = make_flow(client, ws, model_flow(kernel="rbf"))
    r = client.post(f"{ws}/models", json={"flow_id": rbf, "node_id": "m", "name": "x"})
    assert r.status_code == 422 and "support vectors" in r.json()["error"]["message"]
    assert client.get(f"{ws}/models").json() == []


def test_score_endpoint_and_score_block(client, ws):
    fid = make_flow(client, ws, model_flow(kernel="rbf"))
    m = client.post(f"{ws}/models", json={"flow_id": fid, "node_id": "m", "name": "M"}).json()
    r = client.post(
        f"{ws}/models/{m['id']}/score", json={"source": {"kind": "crm", "table": "deals"}}
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["n_rows"] == 160 and b["n_scored"] == 160 and len(b["rows"]) == 160
    assert b["status"] == m["status"] and "score" in b["columns"]
    assert b["summary"]["min"] <= b["summary"]["mean"] <= b["summary"]["max"]
    if m["status"] != "verified":
        assert "not verified" in b["status_note"]
    # a source with no cycle_days column is a clear error
    miss = client.post(
        f"{ws}/models/{m['id']}/score", json={"source": {"kind": "crm", "table": "accounts"}}
    )
    assert miss.status_code == 422 and "cycle_days" in miss.json()["error"]["message"]
    # scoring a flow node
    sc = client.post(
        f"{ws}/models/{m['id']}/score",
        json={"source": {"kind": "flow", "flow_id": fid, "node_id": "d"}},
    )
    assert sc.status_code == 200
    assert (
        client.post(
            f"/api/w/m2/models/{m['id']}/score", json={"source": {"kind": "crm", "table": "deals"}}
        ).status_code
        == 404
    )
    # the score block resolves the saved model when the run starts
    g = {
        "version": 1,
        "nodes": [
            node("d", {"type": "dataset", "dataset": {"source": "crm", "table": "deals"}}),
            node("c", {"type": "score", "model_id": m["id"]}),
        ],
        "edges": [{"id": "e", "source": "d", "target": "c"}],
    }
    run = client.post(f"{ws}/flows/run", json={"graph": g, "target": "c"}).json()["results"]["c"]
    assert run["status"] == "ok", run
    assert run["view"]["kind"] == "score" and run["view"]["status"] == m["status"]
    assert "score" in [c["name"] for c in run["columns"]]
    # another workspace cannot use the model id
    other = client.post("/api/w/m2/flows/run", json={"graph": g, "target": "c"}).json()
    assert other["results"]["c"]["status"] == "error"
