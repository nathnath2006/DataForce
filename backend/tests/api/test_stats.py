from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.demo.generator import generate
from app.demo.loader import load_dataset

pytestmark = pytest.mark.integration


@pytest.fixture
def demo(client: TestClient, db_session) -> str:
    load_dataset(db_session, generate("planted", 5, 60), workspace_slug="demo-s")
    return "/api/w/demo-s"


def test_pipeline_numbers_are_exact(client, demo):
    p = client.get(f"{demo}/stats/pipeline").json()
    assert p["n_deals"] == 60
    assert p["n_open"] + p["n_closed"] == 60 and p["n_won"] + p["n_lost"] == p["n_closed"]
    assert sum(s["count"] for s in p["by_stage"].values()) == 60
    assert set(p["by_stage"]) >= {"prospecting", "closed_won", "closed_lost"}
    assert p["total_amount_eur"] == pytest.approx(
        sum(s["amount_eur"] for s in p["by_stage"].values())
    )
    assert client.get(f"{demo}/deals").json()["total"] == 60


def test_pipeline_empty_workspace(client):
    client.post("/api/workspaces", json={"slug": "empty", "name": "E"})
    p = client.get("/api/w/empty/stats/pipeline").json()
    assert p["n_deals"] == 0 and p["total_amount_eur"] == 0


def test_latest_scan_404_then_scan_then_latest(client, demo):
    r = client.get(f"{demo}/stats/scan/latest")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    scan = client.post(f"{demo}/stats/scan")
    assert scan.status_code == 200
    body = scan.json()
    assert body["run_id"] and body["report"]["n_deals"] == 60
    assert body["report"]["gates"]["min_n"] >= 1
    assert all(f["status"] in ("verified", "not_verified") for f in body["report"]["findings"])
    latest = client.get(f"{demo}/stats/scan/latest").json()
    assert latest["run_id"] == body["run_id"]
    assert latest["report"]["n_deals"] == body["report"]["n_deals"]
    again = client.post(f"{demo}/stats/scan").json()
    assert again["run_id"] != body["run_id"]
    assert client.get(f"{demo}/stats/scan/latest").json()["run_id"] == again["run_id"]


def test_latest_scan_is_workspace_scoped(client, demo):
    client.post(f"{demo}/stats/scan")
    client.post("/api/workspaces", json={"slug": "plain", "name": "P"})
    assert client.get("/api/w/plain/stats/scan/latest").status_code == 404
    assert client.get("/api/w/ghost/stats/pipeline").status_code == 404
