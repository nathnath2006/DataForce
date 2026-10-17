"""Accounts, contacts, org chart and deals through the HTTP API."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture
def ws(client: TestClient) -> str:
    assert client.post("/api/workspaces", json={"slug": "t1", "name": "T1"}).status_code == 201
    return "/api/w/t1"


@pytest.fixture
def other(client: TestClient) -> str:
    assert client.post("/api/workspaces", json={"slug": "t2", "name": "T2"}).status_code == 201
    return "/api/w/t2"


def mk_account(client, ws, name="Acme", **kw) -> dict:
    r = client.post(f"{ws}/accounts", json={"name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def mk_contact(client, ws, account_id, name="Jo", **kw) -> dict:
    r = client.post(f"{ws}/contacts", json={"account_id": account_id, "full_name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def mk_deal(client, ws, account_id, name="Deal", **kw) -> dict:
    body = {"account_id": account_id, "name": name, "created_on": "2026-01-10", **kw}
    r = client.post(f"{ws}/deals", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --- accounts -------------------------------------------------------------------------------
def test_account_crud_and_counts(client, ws):
    acc = mk_account(client, ws, domain="acme.io", segment="smb", country="fr")
    assert acc["source"] == "manual" and acc["country"] == "FR"
    assert (acc["n_contacts"], acc["n_deals"], acc["n_open_deals"]) == (0, 0, 0)
    mk_contact(client, ws, acc["id"])
    d = mk_deal(client, ws, acc["id"])
    mk_deal(client, ws, acc["id"], "Won")
    got = client.get(f"{ws}/accounts/{acc['id']}").json()
    assert (got["n_contacts"], got["n_deals"], got["n_open_deals"]) == (1, 2, 2)
    r = client.put(
        f"{ws}/deals/{d['id']}/stage", json={"stage": "closed_won", "closed_on": "2026-02-01"}
    )
    assert r.status_code == 200
    got = client.get(f"{ws}/accounts/{acc['id']}").json()
    assert got["n_open_deals"] == 1


def test_account_patch_partial_semantics(client, ws):
    acc = mk_account(client, ws, domain="acme.io", industry="SaaS", region="EU")
    r = client.patch(f"{ws}/accounts/{acc['id']}", json={"industry": None, "region": "NA"})
    body = r.json()
    assert r.status_code == 200
    assert (body["name"], body["domain"], body["industry"], body["region"]) == (
        "Acme",
        "acme.io",
        None,
        "NA",
    )
    assert client.patch(f"{ws}/accounts/{acc['id']}", json={}).json()["domain"] == "acme.io"
    r = client.patch(f"{ws}/accounts/{acc['id']}", json={"name": None})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"
    assert client.patch(f"{ws}/accounts/{acc['id']}", json={"name": ""}).status_code == 422
    assert client.patch(f"{ws}/accounts/{acc['id']}", json={"bogus": 1}).status_code == 422


def test_account_list_pagination_search_literal_percent(client, ws):
    for name in ("Alpha 100%", "Beta_co", "Gamma", "Delta"):
        mk_account(client, ws, name)
    page = client.get(f"{ws}/accounts?limit=2&offset=0").json()
    assert page["total"] == 4 and [a["name"] for a in page["items"]] == ["Alpha 100%", "Beta_co"]
    page = client.get(f"{ws}/accounts?limit=2&offset=2").json()
    assert [a["name"] for a in page["items"]] == ["Delta", "Gamma"]
    assert [a["name"] for a in client.get(f"{ws}/accounts", params={"q": "%"}).json()["items"]] == [
        "Alpha 100%"
    ]
    assert [a["name"] for a in client.get(f"{ws}/accounts", params={"q": "_"}).json()["items"]] == [
        "Beta_co"
    ]
    assert client.get(f"{ws}/accounts", params={"q": "GAMMA"}).json()["total"] == 1
    assert client.get(f"{ws}/accounts", params={"q": "x' OR 1=1 --"}).json()["total"] == 0
    assert client.get(f"{ws}/accounts?limit=1001").status_code == 422
    assert client.get(f"{ws}/accounts?limit=0").status_code == 422
    assert client.get(f"{ws}/accounts?offset=-1").status_code == 422


def test_account_segment_filter(client, ws):
    mk_account(client, ws, "S", segment="smb")
    mk_account(client, ws, "E", segment="enterprise")
    items = client.get(f"{ws}/accounts?segment=enterprise").json()["items"]
    assert [a["name"] for a in items] == ["E"]
    assert client.get(f"{ws}/accounts?segment=nope").status_code == 422


def test_account_erase_cascades(client, ws):
    acc = mk_account(client, ws)
    c = mk_contact(client, ws, acc["id"])
    d = mk_deal(client, ws, acc["id"])
    assert client.post(f"{ws}/contacts/{c['id']}/notes", json={"body": "hi"}).status_code == 201
    r = client.delete(f"{ws}/accounts/{acc['id']}")
    assert r.status_code == 204 and r.content == b""
    for path in (f"accounts/{acc['id']}", f"contacts/{c['id']}", f"deals/{d['id']}"):
        assert client.get(f"{ws}/{path}").status_code == 404
    assert client.delete(f"{ws}/accounts/{acc['id']}").status_code == 404


def test_cross_workspace_ids_are_404(client, ws, other):
    acc = mk_account(client, ws)
    c = mk_contact(client, ws, acc["id"])
    d = mk_deal(client, ws, acc["id"])
    foreign = mk_account(client, other, "Foreign")
    reads = [
        f"accounts/{acc['id']}",
        f"accounts/{acc['id']}/org-chart",
        f"contacts/{c['id']}",
        f"deals/{d['id']}",
    ]
    for path in reads:
        assert client.get(f"{other}/{path}").status_code == 404, path
    assert client.patch(f"{other}/accounts/{acc['id']}", json={"industry": "x"}).status_code == 404
    assert client.patch(f"{other}/contacts/{c['id']}", json={"title": "x"}).status_code == 404
    assert client.patch(f"{other}/deals/{d['id']}", json={"name": "x"}).status_code == 404
    assert (
        client.put(f"{other}/deals/{d['id']}/stage", json={"stage": "proposal"}).status_code == 404
    )
    assert (
        client.put(f"{other}/contacts/{c['id']}/reports-to", json={"manager_id": None}).status_code
        == 404
    )
    for kind, i in (("accounts", acc["id"]), ("contacts", c["id"]), ("deals", d["id"])):
        assert client.delete(f"{other}/{kind}/{i}").status_code == 404
    # creating with a foreign parent id
    assert (
        client.post(
            f"{other}/contacts", json={"account_id": acc["id"], "full_name": "x"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{other}/deals",
            json={"account_id": acc["id"], "name": "x", "created_on": "2026-01-01"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{ws}/deals",
            json={"account_id": foreign["id"], "name": "x", "created_on": "2026-01-01"},
        ).status_code
        == 404
    )
    # nothing leaked into lists, and the originals survive
    assert client.get(f"{other}/contacts?account_id={acc['id']}").json()["total"] == 0
    assert client.get(f"{ws}/accounts/{acc['id']}").status_code == 200
    assert client.get("/api/w/ghost/accounts").status_code == 404
    assert client.get(f"{ws}/accounts/{uuid.uuid4()}").status_code == 404
    assert client.get(f"{ws}/accounts/not-a-uuid").status_code == 422


# --- contacts -------------------------------------------------------------------------------
def test_contact_crud_patch_and_filters(client, ws):
    a, b = mk_account(client, ws, "A"), mk_account(client, ws, "B")
    c = mk_contact(client, ws, a["id"], "Jane Doe", title="CTO")
    assert c["account_name"] == "A" and c["reports_to_name"] is None
    assert (c["n_direct_reports"], c["n_notes"], c["n_channels"]) == (0, 0, 0)
    mk_contact(client, ws, b["id"], "Other")
    r = client.patch(f"{ws}/contacts/{c['id']}", json={"title": None})
    assert r.json()["title"] is None and r.json()["full_name"] == "Jane Doe"
    assert client.patch(f"{ws}/contacts/{c['id']}", json={"full_name": None}).status_code == 422
    assert client.patch(f"{ws}/contacts/{c['id']}", json={"reports_to_id": None}).status_code == 422
    page = client.get(f"{ws}/contacts", params={"account_id": a["id"]}).json()
    assert page["total"] == 1
    assert client.get(f"{ws}/contacts", params={"q": "doe"}).json()["total"] == 1
    assert client.get(f"{ws}/contacts", params={"q": "%"}).json()["total"] == 0
    assert client.get(f"{ws}/contacts?limit=1").json()["total"] == 2
    assert len(client.get(f"{ws}/contacts?limit=1").json()["items"]) == 1


def test_reports_to_and_cycles(client, ws):
    acc = mk_account(client, ws)
    ceo = mk_contact(client, ws, acc["id"], "CEO")
    vp = mk_contact(client, ws, acc["id"], "VP", reports_to_id=ceo["id"])
    rep = mk_contact(client, ws, acc["id"], "Rep")
    assert vp["reports_to_name"] == "CEO"
    r = client.put(f"{ws}/contacts/{rep['id']}/reports-to", json={"manager_id": vp["id"]})
    assert r.status_code == 200 and r.json()["reports_to_id"] == vp["id"]
    assert client.get(f"{ws}/contacts/{ceo['id']}").json()["n_direct_reports"] == 1
    for victim, boss in ((ceo, rep), (ceo, ceo), (ceo, vp)):
        r = client.put(f"{ws}/contacts/{victim['id']}/reports-to", json={"manager_id": boss["id"]})
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_input"
    assert (
        client.put(f"{ws}/contacts/{rep['id']}/reports-to", json={"manager_id": None}).json()[
            "reports_to_id"
        ]
        is None
    )
    stranger = mk_contact(client, ws, mk_account(client, ws, "B")["id"], "S")
    r = client.put(f"{ws}/contacts/{stranger['id']}/reports-to", json={"manager_id": ceo["id"]})
    assert r.status_code == 422  # other account
    assert client.put(f"{ws}/contacts/{rep['id']}/reports-to", json={}).status_code == 422


def test_org_chart(client, ws):
    acc = mk_account(client, ws, "Org")
    ceo = mk_contact(client, ws, acc["id"], "CEO")
    mk_contact(client, ws, acc["id"], "VP", reports_to_id=ceo["id"])
    chart = client.get(f"{ws}/accounts/{acc['id']}/org-chart").json()
    assert chart["account_name"] == "Org" and len(chart["nodes"]) == 2
    nodes = {n["full_name"]: n for n in chart["nodes"]}
    assert nodes["VP"]["reports_to_id"] == ceo["id"] and nodes["CEO"]["reports_to_id"] is None
    assert nodes["CEO"]["source"] == "manual"


def test_contact_erase_cascades_notes_and_unlinks_reports(client, ws):
    acc = mk_account(client, ws)
    boss = mk_contact(client, ws, acc["id"], "Boss")
    rep = mk_contact(client, ws, acc["id"], "Rep", reports_to_id=boss["id"])
    note = client.post(f"{ws}/contacts/{boss['id']}/notes", json={"body": "secret"}).json()
    assert client.delete(f"{ws}/contacts/{boss['id']}").status_code == 204
    assert client.get(f"{ws}/contacts/{boss['id']}").status_code == 404
    assert client.get(f"{ws}/notes/{note['id']}/history").status_code == 404
    assert client.get(f"{ws}/contacts/{rep['id']}").json()["reports_to_id"] is None


# --- deals ----------------------------------------------------------------------------------
def test_deal_create_get_names_and_cycle_days(client, ws):
    acc = mk_account(client, ws, "Acme")
    user = client.post(f"{ws}/users", json={"display_name": "Ann"}).json()
    d = mk_deal(
        client, ws, acc["id"], owner_id=user["id"], amount_eur="1500.50", lead_source="inbound"
    )
    assert (d["account_name"], d["owner_name"], d["is_closed"], d["cycle_days"]) == (
        "Acme",
        "Ann",
        False,
        None,
    )
    assert d["stage"] == "prospecting" and d["source"] == "manual"
    r = client.put(
        f"{ws}/deals/{d['id']}/stage", json={"stage": "closed_won", "closed_on": "2026-02-09"}
    )
    out = r.json()
    assert out["is_closed"] is True and out["cycle_days"] == 30
    r = client.put(
        f"{ws}/deals/{d['id']}/stage", json={"stage": "closed_won", "closed_on": "2025-01-01"}
    )
    assert r.status_code == 422
    assert client.put(f"{ws}/deals/{d['id']}/stage", json={"stage": "nope"}).status_code == 422
    reopened = client.put(f"{ws}/deals/{d['id']}/stage", json={"stage": "negotiation"}).json()
    assert reopened["closed_on"] is None and reopened["cycle_days"] is None


def test_deal_patch_partial_dates_and_owner(client, ws, other):
    acc = mk_account(client, ws)
    mine = client.post(f"{ws}/users", json={"display_name": "Me"}).json()
    foreign = client.post(f"{other}/users", json={"display_name": "Them"}).json()
    d = mk_deal(client, ws, acc["id"], amount_eur="10", lost_reason="x")
    r = client.patch(f"{ws}/deals/{d['id']}", json={"owner_id": mine["id"], "amount_eur": None})
    assert r.status_code == 200
    assert (r.json()["owner_name"], r.json()["amount_eur"], r.json()["name"]) == (
        "Me",
        None,
        "Deal",
    )
    assert (
        client.patch(f"{ws}/deals/{d['id']}", json={"owner_id": foreign["id"]}).status_code == 404
    )
    assert (
        client.patch(f"{ws}/deals/{d['id']}", json={"owner_id": None}).json()["owner_name"] is None
    )
    assert client.patch(f"{ws}/deals/{d['id']}", json={"stage": "proposal"}).status_code == 422
    client.put(
        f"{ws}/deals/{d['id']}/stage", json={"stage": "closed_lost", "closed_on": "2026-01-20"}
    )
    assert (
        client.patch(f"{ws}/deals/{d['id']}", json={"created_on": "2026-02-01"}).status_code == 422
    )
    assert client.patch(f"{ws}/deals/{d['id']}", json={"name": None}).status_code == 422
    assert client.patch(f"{ws}/deals/{d['id']}", json={"amount_eur": "-5"}).status_code == 422


def test_deal_list_filters_order_and_delete(client, ws):
    a, b = mk_account(client, ws, "A"), mk_account(client, ws, "B")
    me = client.post(f"{ws}/users", json={"display_name": "Me"}).json()
    old = mk_deal(client, ws, a["id"], "100% old", created_on="2025-05-01", lead_source="referral")
    new = mk_deal(client, ws, b["id"], "new", created_on="2026-05-01", owner_id=me["id"])
    page = client.get(f"{ws}/deals").json()
    assert [x["id"] for x in page["items"]] == [new["id"], old["id"]] and page["total"] == 2
    assert client.get(f"{ws}/deals", params={"account_id": a["id"]}).json()["total"] == 1
    assert (
        client.get(f"{ws}/deals", params={"lead_source": "referral"}).json()["items"][0]["id"]
        == old["id"]
    )
    assert (
        client.get(f"{ws}/deals", params={"owner_id": me["id"]}).json()["items"][0]["id"]
        == new["id"]
    )
    assert client.get(f"{ws}/deals", params={"stage": "prospecting"}).json()["total"] == 2
    assert client.get(f"{ws}/deals", params={"stage": "closed_won"}).json()["total"] == 0
    assert [x["id"] for x in client.get(f"{ws}/deals", params={"q": "%"}).json()["items"]] == [
        old["id"]
    ]
    assert len(client.get(f"{ws}/deals?limit=1&offset=1").json()["items"]) == 1
    assert client.delete(f"{ws}/deals/{new['id']}").status_code == 204
    assert client.get(f"{ws}/deals/{new['id']}").status_code == 404
    assert client.get(f"{ws}/deals").json()["total"] == 1


def test_create_validation_errors(client, ws):
    acc = mk_account(client, ws)
    assert client.post(f"{ws}/accounts", json={"name": ""}).status_code == 422
    assert client.post(f"{ws}/accounts", json={"name": "x", "source": "demo"}).status_code == 422
    bad = {
        "account_id": acc["id"],
        "name": "d",
        "created_on": "2026-03-01",
        "closed_on": "2026-01-01",
    }
    assert client.post(f"{ws}/deals", json=bad).status_code == 422


@pytest.mark.parametrize("path", ["accounts", "contacts", "deals"])
def test_list_params_are_bounded_422_never_500(client, ws, path):
    assert client.get(f"{ws}/{path}?offset=99999999999999999999").status_code == 422
    assert client.get(f"{ws}/{path}?offset=1000001").status_code == 422
    assert client.get(f"{ws}/{path}?offset=1000000").status_code == 200
    assert client.get(f"{ws}/{path}", params={"q": "a\x00b"}).status_code == 422
    assert client.get(f"{ws}/{path}", params={"q": "a\x07b"}).status_code == 422
    assert client.get(f"{ws}/{path}", params={"q": "x" * 201}).status_code == 422
    assert client.get(f"{ws}/{path}", params={"q": "x" * 200}).status_code == 200


def test_employee_count_too_big_is_422(client, ws):
    r = client.post(f"{ws}/accounts", json={"name": "E", "employee_count": 10**12})
    assert r.status_code == 422
