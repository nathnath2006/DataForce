"""Data-quality endpoint: every count checked against raw SQL."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.models import Contact, OrgProposal

pytestmark = pytest.mark.integration


def mk(client, slug):
    assert client.post("/api/workspaces", json={"slug": slug, "name": slug}).status_code == 201
    return f"/api/w/{slug}"


def seg(body, cid):
    c = next(c for c in body["checks"] if c["id"] == cid)
    assert sum(s["count"] for s in c["segments"]) == c["total"]
    return c["total"], {s["kind"]: s["count"] for s in c["segments"]}


def test_empty_workspace_zeros(client: TestClient):
    ws = mk(client, "q-empty")
    body = client.get(f"{ws}/quality").json()
    assert [c["id"] for c in body["checks"]] == ["managers", "titles", "amounts", "companies"]
    for c in body["checks"]:
        assert c["total"] == 0 and all(s["count"] == 0 for s in c["segments"])


def seed(client, db, ws):
    acc = client.post(f"{ws}/accounts", json={"name": "A"}).json()["id"]
    acc2 = client.post(f"{ws}/accounts", json={"name": "B"}).json()["id"]
    co = client.post(f"{ws}/companies", json={"name": "Co SAS"}).json()["id"]
    assert client.put(f"{ws}/accounts/{acc}/company", json={"company_id": co}).status_code == 200
    cs = []
    for i in range(6):
        r = client.post(f"{ws}/contacts", json={"account_id": acc, "full_name": f"C{i}"})
        assert r.status_code == 201, r.text
        cs.append(uuid.UUID(r.json()["id"]))
    spec = [
        ("dictionary", "sales", None),
        ("manual", "tech", None),
        ("llm", "sales", None),
        ("dictionary", "hr", "odd"),
        ("dictionary", "unknown", None),
        (None, None, None),
    ]
    for cid, (src, fn, flag) in zip(cs, spec, strict=True):
        c = db.get(Contact, cid)
        c.title_source, c.title_function, c.title_flag = src, fn, flag
    db.get(Contact, cs[1]).reports_to_id = cs[0]
    db.get(Contact, cs[2]).reports_to_id = cs[0]
    ws_id = db.get(Contact, cs[0]).workspace_id
    db.add(
        OrgProposal(
            workspace_id=ws_id,
            account_id=uuid.UUID(acc),
            contact_id=cs[3],
            kind="reports_to",
            manager_id=cs[0],
            origin="rule",
            status="proposed",
        )
    )
    db.add(
        OrgProposal(  # rejected: does not count as an open suggestion
            workspace_id=ws_id,
            account_id=uuid.UUID(acc),
            contact_id=cs[4],
            kind="reports_to",
            manager_id=cs[0],
            origin="rule",
            status="rejected",
        )
    )
    for name, stage, amt in [
        ("d1", "proposal", 100),
        ("d2", "proposal", None),
        ("d3", "closed_won", None),
        ("d4", "closed_lost", 5),
        ("d5", "prospecting", None),
    ]:
        body = {
            "account_id": acc2,
            "name": name,
            "stage": stage,
            "amount_eur": amt,
            "created_on": "2020-01-01",
        }
        if stage.startswith("closed"):
            body["closed_on"] = "2099-01-01"
        r = client.post(f"{ws}/deals", json=body)
        assert r.status_code == 201, r.text
    db.flush()


def test_counts_match_sql(client: TestClient, db_session):
    ws = mk(client, "q-one")
    other = mk(client, "q-two")
    seed(client, db_session, ws)
    seed(client, db_session, other)
    # extra rows in the other workspace must not leak
    body = client.get(f"{ws}/quality").json()
    assert seg(body, "managers") == (6, {"ok": 2, "warn": 1, "unknown": 3})
    assert seg(body, "titles") == (6, {"ok": 2, "warn": 2, "unknown": 2})
    assert seg(body, "amounts") == (5, {"ok": 2, "bad": 2, "unknown": 1})
    assert seg(body, "companies") == (2, {"ok": 1, "unknown": 1})

    def one(sql):
        return db_session.execute(text(sql), {"s": "q-one"}).scalar_one()

    wid = "(SELECT id FROM workspace WHERE slug = :s)"
    assert one(f"SELECT count(*) FROM contact WHERE workspace_id = {wid}") == 6
    assert (
        one(
            f"SELECT count(*) FROM contact WHERE workspace_id = {wid} AND reports_to_id IS NOT NULL"
        )
        == 2
    )
    assert one(f"SELECT count(*) FROM deal WHERE workspace_id = {wid} AND amount_eur IS NULL") == 3
    assert (
        one(f"SELECT count(*) FROM account WHERE workspace_id = {wid} AND company_id IS NULL") == 1
    )
    assert (
        one(
            f"SELECT count(*) FROM contact WHERE workspace_id = {wid} AND "
            "(title_source = 'llm' OR title_flag IS NOT NULL)"
        )
        == 2
    )
    assert client.get(f"{other}/quality").json() == client.get(f"{other}/quality").json()


def test_unknown_workspace_404(client: TestClient):
    assert client.get("/api/w/nope/quality").status_code == 404
