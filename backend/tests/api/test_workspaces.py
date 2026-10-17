from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.demo.generator import generate
from app.demo.loader import load_dataset

pytestmark = pytest.mark.integration


def test_create_list_and_conflict(client: TestClient):
    r = client.post("/api/workspaces", json={"slug": "acme-co", "name": "Acme Co"})
    assert r.status_code == 201
    body = r.json()
    assert body["slug"] == "acme-co" and body["is_demo"] is False
    assert (body["n_accounts"], body["n_contacts"], body["n_deals"]) == (0, 0, 0)
    assert (
        client.post("/api/workspaces", json={"slug": "acme-co", "name": "again"}).status_code == 409
    )
    listed = client.get("/api/workspaces").json()
    assert "acme-co" in [w["slug"] for w in listed]


def test_create_validation(client: TestClient):
    for body in (
        {"slug": "Bad Slug", "name": "x"},
        {"slug": "ok", "name": ""},
        {"slug": "ok", "name": "x", "is_demo": True},  # unknown field
    ):
        r = client.post("/api/workspaces", json=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"


def test_list_order_and_counts(client: TestClient, db_session):
    load_dataset(db_session, generate("noise", 3, 60), workspace_slug="aa-demo")
    client.post("/api/workspaces", json={"slug": "zz-real", "name": "Real"})
    listed = client.get("/api/workspaces").json()
    slugs = [w["slug"] for w in listed]
    assert slugs.index("zz-real") < slugs.index("aa-demo")  # real first
    demo = next(w for w in listed if w["slug"] == "aa-demo")
    assert demo["is_demo"] is True and demo["n_deals"] == 60 and demo["n_accounts"] > 0


def test_users(client: TestClient):
    client.post("/api/workspaces", json={"slug": "team", "name": "Team"})
    r = client.post("/api/w/team/users", json={"display_name": "Ann", "email": "a@x.io"})
    assert r.status_code == 201 and r.json()["role"] == "user"
    assert (
        client.post("/api/w/team/users", json={"display_name": "B", "email": "a@x.io"}).status_code
        == 409
    )
    assert [u["display_name"] for u in client.get("/api/w/team/users").json()] == ["Ann"]
    assert client.get("/api/w/nope/users").status_code == 404
