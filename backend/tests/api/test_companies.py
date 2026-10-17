"""Companies, lookup and registry endpoints (registry mocked with respx)."""

from __future__ import annotations

import copy

import httpx
import pytest
import respx

from app.registry import client as reg
from tests.api.test_crm import mk_account, mk_contact, mk_deal
from tests.registry.test_client import SAMPLE

pytestmark = pytest.mark.integration

REG = "https://recherche-entreprises.api.gouv.fr/search"


@pytest.fixture
def ws(client) -> str:
    assert client.post("/api/workspaces", json={"slug": "t1", "name": "T1"}).status_code == 201
    return "/api/w/t1"


@pytest.fixture
def other(client) -> str:
    assert client.post("/api/workspaces", json={"slug": "t2", "name": "T2"}).status_code == 201
    return "/api/w/t2"


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    monkeypatch.setattr(reg, "_min_interval_s", 0.0)


def mk_company(client, ws, name="Acme SAS", **kw) -> dict:
    r = client.post(f"{ws}/companies", json={"name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def link(client, ws, account_id, company_id):
    return client.put(f"{ws}/accounts/{account_id}/company", json={"company_id": company_id})


def test_create_list_patch_delete(client, ws):
    c = mk_company(client, ws, siren="123456789", city="Lyon", country="fr")
    assert c["source"] == "manual" and c["country"] == "FR"
    assert (c["n_accounts"], c["n_deals"], c["interacted"], c["last_interaction"]) == (
        0,
        0,
        False,
        None,
    )
    assert (
        client.post(f"{ws}/companies", json={"name": "Dup", "siren": "123456789"}).status_code
        == 409
    )
    assert client.post(f"{ws}/companies", json={"name": "x", "siren": "12"}).status_code == 422
    assert client.post(f"{ws}/companies", json={"name": "x", "bogus": 1}).status_code == 422
    page = client.get(f"{ws}/companies", params={"q": "acme"}).json()
    assert page["total"] == 1 and page["items"][0]["id"] == c["id"]
    assert client.get(f"{ws}/companies", params={"q": "123456"}).json()["total"] == 1
    assert client.get(f"{ws}/companies", params={"q": "%"}).json()["total"] == 0
    r = client.patch(f"{ws}/companies/{c['id']}", json={"city": None, "domain": "acme.io"})
    assert r.json()["city"] is None and r.json()["domain"] == "acme.io"
    assert client.patch(f"{ws}/companies/{c['id']}", json={"name": None}).status_code == 422
    assert client.patch(f"{ws}/companies/{c['id']}", json={"siren": "1"}).status_code == 422
    assert client.delete(f"{ws}/companies/{c['id']}").status_code == 204
    assert client.get(f"{ws}/companies/{c['id']}").status_code == 404


def test_link_unlink_and_delete_unlinks(client, ws):
    c = mk_company(client, ws)
    a1, a2 = mk_account(client, ws, "A1"), mk_account(client, ws, "A2")
    out = link(client, ws, a1["id"], c["id"]).json()
    assert out["company_id"] == c["id"] and out["company_name"] == "Acme SAS"
    link(client, ws, a2["id"], c["id"])
    assert client.get(f"{ws}/companies/{c['id']}").json()["company"]["n_accounts"] == 2
    assert client.get(f"{ws}/accounts/{a1['id']}").json()["company_name"] == "Acme SAS"
    listed = client.get(f"{ws}/accounts").json()["items"]
    assert {a["company_name"] for a in listed} == {"Acme SAS"}
    out = link(client, ws, a1["id"], None).json()
    assert out["company_id"] is None and out["company_name"] is None
    assert client.delete(f"{ws}/companies/{c['id']}").status_code == 204
    after = client.get(f"{ws}/accounts/{a2['id']}").json()
    assert after["company_id"] is None and after["company_name"] is None


def test_360_content_and_last_interaction(client, ws):
    c = mk_company(client, ws)
    a = mk_account(client, ws, "Acme Conseil")
    b = mk_account(client, ws, "Acme Digital")
    loose = mk_account(client, ws, "Elsewhere")
    link(client, ws, a["id"], c["id"])
    link(client, ws, b["id"], c["id"])
    ct = mk_contact(client, ws, a["id"], "Jo")
    mk_contact(client, ws, loose["id"], "Other")
    d = mk_deal(client, ws, a["id"], "Big", amount_eur="1000", created_on="2026-01-10")
    client.put(
        f"{ws}/deals/{d['id']}/stage", json={"stage": "closed_won", "closed_on": "2026-03-01"}
    )
    mk_deal(client, ws, b["id"], "Open", amount_eur="500", created_on="2026-02-01")
    mk_deal(client, ws, loose["id"], "Not mine", created_on="2026-02-01")
    body = "x" * 500
    n = client.post(f"{ws}/contacts/{ct['id']}/notes", json={"body": body})
    assert n.status_code == 201
    cm = client.post(f"{ws}/accounts/{b['id']}/comments", json={"body": "hello"})
    assert cm.status_code == 201

    r = client.get(f"{ws}/companies/{c['id']}")
    assert r.status_code == 200
    j = r.json()
    co = j["company"]
    assert (co["n_accounts"], co["n_contacts"], co["n_deals"], co["n_open_deals"]) == (2, 1, 2, 1)
    assert float(co["won_amount_eur"]) == 1000.0
    assert co["interacted"] is True
    # notes/comments are created now (2026+), later than the deal dates
    assert co["last_interaction"] >= "2026-03-01"
    assert {x["id"] for x in j["accounts"]} == {a["id"], b["id"]}
    assert [x["full_name"] for x in j["contacts"]] == ["Jo"]
    assert {x["name"] for x in j["deals"]} == {"Big", "Open"}
    kinds = {x["kind"] for x in j["activity"]}
    assert kinds == {"note", "comment", "deal_created", "deal_closed"}
    note = next(x for x in j["activity"] if x["kind"] == "note")
    assert len(note["excerpt"]) <= 200 and note["contact_id"] == ct["id"]
    ats = [x["at"] for x in j["activity"]]
    assert len(ats) == 5 and ats[0] >= ats[-1]
    assert all(x["account_id"] != loose["id"] for x in j["activity"])


def test_360_limits(client, ws, db_session):
    from datetime import date

    from app.db.models import Account, Company, Contact, Deal, Workspace

    wsid = db_session.query(Workspace).filter_by(slug="t1").one().id
    co = Company(workspace_id=wsid, name="Big")
    db_session.add(co)
    db_session.flush()
    acc = Account(workspace_id=wsid, name="A", company_id=co.id)
    db_session.add(acc)
    db_session.flush()
    db_session.add_all(
        Contact(workspace_id=wsid, account_id=acc.id, full_name=f"C{i}") for i in range(210)
    )
    db_session.add_all(
        Deal(workspace_id=wsid, account_id=acc.id, name=f"D{i}", created_on=date(2026, 1, 1))
        for i in range(510)
    )
    db_session.commit()
    j = client.get(f"{ws}/companies/{co.id}").json()
    assert len(j["contacts"]) == 200 and len(j["deals"]) == 500 and len(j["activity"]) == 50
    assert j["company"]["n_contacts"] == 210 and j["company"]["n_deals"] == 510


def test_last_interaction_none_without_activity(client, ws):
    c = mk_company(client, ws)
    a = mk_account(client, ws)
    mk_contact(client, ws, a["id"])
    link(client, ws, a["id"], c["id"])
    co = client.get(f"{ws}/companies/{c['id']}").json()["company"]
    assert co["last_interaction"] is None and co["interacted"] is False
    mk_deal(client, ws, a["id"], created_on="2025-05-05")
    co = client.get(f"{ws}/companies/{c['id']}").json()["company"]
    assert co["last_interaction"] == "2025-05-05" and co["interacted"] is True


def test_lookup(client, ws):
    c = mk_company(client, ws, "Alderon SAS", siren="111111111", domain="alderon.example")
    a = mk_account(client, ws, "Alderon Conseil")
    link(client, ws, a["id"], c["id"])
    loose = mk_account(client, ws, "Alderon Loose")
    r = client.get(f"{ws}/lookup", params={"q": "alderon"}).json()
    assert [x["id"] for x in r["companies"]] == [c["id"]]
    assert [x["id"] for x in r["accounts"]] == [loose["id"]]  # linked accounts are not repeated
    assert r["interacted"] is False
    mk_deal(client, ws, loose["id"])
    assert client.get(f"{ws}/lookup", params={"q": "alderon"}).json()["interacted"] is True
    assert (
        client.get(f"{ws}/lookup", params={"q": "111111"}).json()["companies"][0]["id"] == c["id"]
    )
    assert client.get(f"{ws}/lookup", params={"q": "alderon.ex"}).json()["companies"]
    assert client.get(f"{ws}/lookup", params={"q": ""}).json() == {
        "companies": [],
        "accounts": [],
        "interacted": False,
    }


@respx.mock
def test_registry_search_flags_in_crm(client, ws):
    c = mk_company(client, ws, "Dataiku", siren="791012081")
    sole = copy.deepcopy(SAMPLE) | {"siren": "222222222", "dirigeants": [{"nom": "LEAK"}]}
    route = respx.get(REG).mock(return_value=httpx.Response(200, json={"results": [SAMPLE, sole]}))
    r = client.get(f"{ws}/registry/search", params={"q": "dataiku"})
    assert r.status_code == 200
    rows = r.json()
    assert [x["siren"] for x in rows] == ["791012081", "222222222"]
    assert rows[0]["in_crm_company_id"] == c["id"] and rows[1]["in_crm_company_id"] is None
    assert "LEAK" not in r.text and "dirigeants" not in r.text
    assert route.call_count == 1
    assert client.get(f"{ws}/registry/search", params={"q": "a" * 101}).status_code == 422
    assert client.get(f"{ws}/registry/search").status_code == 422


@respx.mock
def test_registry_errors_are_502(client, ws):
    respx.get(REG).mock(side_effect=httpx.ConnectTimeout("t"))
    r = client.get(f"{ws}/registry/search", params={"q": "x"})
    assert r.status_code == 502 and r.json()["error"]["code"] == "connector_error"


@respx.mock
def test_from_registry_and_duplicate(client, ws):
    respx.get(REG).mock(return_value=httpx.Response(200, json={"results": [SAMPLE]}))
    r = client.post(
        f"{ws}/companies/from-registry", json={"siren": "791012081", "create_account": True}
    )
    assert r.status_code == 201, r.text
    co = r.json()
    assert co["source"] == "registry" and co["siren"] == "791012081" and co["country"] == "FR"
    assert co["naf_code"] == "58.29C" and co["registry_checked_at"] and co["n_accounts"] == 1
    accs = client.get(f"{ws}/accounts").json()["items"]
    assert [a["company_id"] for a in accs] == [co["id"]]
    dup = client.post(
        f"{ws}/companies/from-registry", json={"siren": "791012081", "create_account": False}
    )
    assert dup.status_code == 409
    nf = client.post(
        f"{ws}/companies/from-registry", json={"siren": "999999999", "create_account": False}
    )
    assert nf.status_code == 404
    assert (
        client.post(
            f"{ws}/companies/from-registry", json={"siren": "1", "create_account": False}
        ).status_code
        == 422
    )


@respx.mock
def test_from_registry_protected_has_no_address(client, ws):
    prot = copy.deepcopy(SAMPLE)
    prot["statut_diffusion"] = "P"
    respx.get(REG).mock(return_value=httpx.Response(200, json={"results": [prot]}))
    co = client.post(
        f"{ws}/companies/from-registry", json={"siren": "791012081", "create_account": False}
    ).json()
    assert co["address_line"] is None and co["city"] is None and co["name"] == "DATAIKU"


@respx.mock
def test_refresh_registry(client, ws):
    manual = mk_company(client, ws, "Old name", siren="791012081")
    nosiren = mk_company(client, ws, "No siren")
    assert client.post(f"{ws}/companies/{nosiren['id']}/refresh-registry").status_code == 422
    respx.get(REG).mock(return_value=httpx.Response(200, json={"results": [SAMPLE]}))
    r = client.post(f"{ws}/companies/{manual['id']}/refresh-registry")
    assert r.status_code == 200
    assert r.json()["name"] == "DATAIKU" and r.json()["registry_checked_at"]
    assert r.json()["source"] == "manual"


@respx.mock
def test_refresh_not_found_and_error(client, ws):
    c = mk_company(client, ws, siren="333333333")
    respx.get(REG).mock(return_value=httpx.Response(200, json={"results": []}))
    assert client.post(f"{ws}/companies/{c['id']}/refresh-registry").status_code == 404
    respx.get(REG).mock(return_value=httpx.Response(500))
    assert client.post(f"{ws}/companies/{c['id']}/refresh-registry").status_code == 502


@respx.mock
def test_cross_workspace_404(client, ws, other):
    c = mk_company(client, ws, siren="791012081")
    a = mk_account(client, ws)
    ob = mk_account(client, other, "Other acct")
    assert client.get(f"{other}/companies/{c['id']}").status_code == 404
    assert client.patch(f"{other}/companies/{c['id']}", json={"city": "x"}).status_code == 404
    assert client.delete(f"{other}/companies/{c['id']}").status_code == 404
    assert client.post(f"{other}/companies/{c['id']}/refresh-registry").status_code == 404
    assert link(client, other, a["id"], c["id"]).status_code == 404  # account of another workspace
    assert link(client, other, ob["id"], c["id"]).status_code == 404  # company of another workspace
    assert client.get(f"{other}/companies").json()["total"] == 0
    assert client.get(f"{other}/lookup", params={"q": "acme"}).json()["companies"] == []
    respx.get(REG).mock(return_value=httpx.Response(200, json={"results": [SAMPLE]}))
    flagged = client.get(f"{other}/registry/search", params={"q": "d"}).json()
    assert flagged[0]["in_crm_company_id"] is None
    # same SIREN may exist in another workspace
    ok = client.post(
        f"{other}/companies/from-registry", json={"siren": "791012081", "create_account": False}
    )
    assert ok.status_code == 201
