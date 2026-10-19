from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

SRC = {"kind": "crm", "table": "deals"}


def viz(i="v1", **kw):
    return {
        "id": i,
        "type": "bar",
        "title": "Pipeline",
        "source": SRC,
        "slots": {"category": "stage", "values": [{"column": "*", "agg": "count"}]},
        **kw,
    }


def spec(n_viz=1):
    vs = [viz(f"v{i}") for i in range(n_viz)]
    return {
        "version": 1,
        "canvases": [
            {
                "name": "Main",
                "filters": [{"column": "segment", "op": "eq", "value": "smb"}],
                "layout": [
                    {"viz_id": v["id"], "x": 0, "y": i, "w": 6, "h": 4} for i, v in enumerate(vs)
                ],
                "visualizations": vs,
            }
        ],
    }


@pytest.fixture
def ws(client):
    client.post("/api/workspaces", json={"slug": "w1", "name": "W1"})
    client.post("/api/workspaces", json={"slug": "w2", "name": "W2"})
    return "/api/w/w1"


def test_crud_duplicate_isolation(client, ws):
    r = client.post(f"{ws}/workbooks", json={"name": "WB", "spec": spec()})
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    assert client.post(f"{ws}/workbooks", json={"name": "E"}).json()["spec"]["canvases"] == []
    assert {s["name"]: s["n_canvases"] for s in client.get(f"{ws}/workbooks").json()} == {
        "WB": 1,
        "E": 0,
    }
    got = client.get(f"{ws}/workbooks/{wid}").json()
    assert got["spec"]["canvases"][0]["visualizations"][0]["options"]["limit"] == 200
    p = client.patch(f"{ws}/workbooks/{wid}", json={"name": "Renamed"}).json()
    assert p["name"] == "Renamed" and len(p["spec"]["canvases"]) == 1
    p = client.patch(f"{ws}/workbooks/{wid}", json={"spec": {"canvases": []}}).json()
    assert p["spec"]["canvases"] == [] and p["name"] == "Renamed"
    d = client.post(f"{ws}/workbooks/{wid}/duplicate")
    assert d.status_code == 201 and d.json()["name"] == "Renamed (copy)" and d.json()["id"] != wid
    assert client.get("/api/w/w2/workbooks").json() == []
    assert client.get(f"/api/w/w2/workbooks/{wid}").status_code == 404
    assert client.patch(f"/api/w/w2/workbooks/{wid}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/w/w2/workbooks/{wid}").status_code == 404
    assert client.post(f"/api/w/w2/workbooks/{wid}/duplicate").status_code == 404
    assert client.delete(f"{ws}/workbooks/{wid}").status_code == 204
    assert client.get(f"{ws}/workbooks/{wid}").status_code == 404


def test_caps(client, ws):
    def post(s):
        return client.post(f"{ws}/workbooks", json={"name": "x", "spec": s}).status_code

    canvas = spec()["canvases"][0]
    assert post({"canvases": [canvas] * 12}) == 201
    assert post({"canvases": [canvas] * 13}) == 422
    assert post(spec(30)) == 201
    assert post(spec(31)) == 422


def test_validation(client, ws):
    def post(mut):
        s = spec()
        mut(s["canvases"][0])
        return client.post(f"{ws}/workbooks", json={"name": "x", "spec": s}).status_code

    assert post(lambda c: c["visualizations"][0].update(type="bubble")) == 422
    assert post(lambda c: c["layout"][0].update(w=13)) == 422
    assert post(lambda c: c["layout"][0].update(x=8, w=6)) == 422  # overflows the grid
    assert post(lambda c: c["layout"][0].update(viz_id="ghost")) == 422
    assert post(lambda c: c["visualizations"].append(viz("v0"))) == 422  # duplicate id
    assert (
        post(lambda c: c["visualizations"][0].setdefault("options", {}).update(limit=9999)) == 422
    )
    assert (
        post(lambda c: c["visualizations"][0].setdefault("options", {}).update(js="alert(1)"))
        == 422
    )
    assert post(lambda c: c["visualizations"][0].update(id="a b")) == 422
    assert (
        post(
            lambda c: c["visualizations"][0]["slots"].update(values=[{"column": "*", "agg": "sum"}])
        )
        == 422
    )
    assert post(lambda c: c.update(name="")) == 422
    assert post(lambda c: c.update(unknown=1)) == 422
    assert client.post(f"{ws}/workbooks", json={"name": "   "}).status_code == 422


def test_spec_and_filter_bounds(client, ws):
    big_list = {"column": "segment", "op": "in", "value": list(range(501))}
    s = spec()
    s["canvases"][0]["filters"] = [big_list]
    assert client.post(f"{ws}/workbooks", json={"name": "B", "spec": s}).status_code == 422
    s["canvases"][0]["filters"] = [{"column": "segment", "op": "eq", "value": "x" * 1001}]
    assert client.post(f"{ws}/workbooks", json={"name": "B", "spec": s}).status_code == 422
    from pydantic import ValidationError

    from app.api.schemas_viz import WorkbookSpec

    s["canvases"][0]["filters"] = [
        {"column": "segment", "op": "in", "value": ["y" * 1000] * 500} for _ in range(3)
    ]
    with pytest.raises(ValidationError, match="larger than"):
        WorkbookSpec.model_validate(s)
