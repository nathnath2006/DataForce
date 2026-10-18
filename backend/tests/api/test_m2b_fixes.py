"""SR12 fixes: erasure of contacts (proposals, transcripts), stale accept, ambiguous rejections,
chunk cap, title AI budget."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.api.routes.titles import get_title_factory
from app.db.models import Contact, Document, DocumentChunk, OrgProposal
from app.llm.errors import LLMError
from app.llm.fake import FakeLLM
from app.services import titles as title_service
from app.titles.ai import TitleAnswer
from tests.api.test_orgchart import add_doc, by_contact, mk_contact, proposals, propose, team  # noqa: F401

pytestmark = pytest.mark.integration


@pytest.fixture
def ws(client):
    assert client.post("/api/workspaces", json={"slug": "o1", "name": "O1"}).status_code == 201
    return "/api/w/o1"


def account(client, ws, name="Acme"):
    return client.post(f"{ws}/accounts", json={"name": name}).json()["id"]


def person(client, ws, acc, name):
    r = client.post(f"{ws}/contacts", json={"account_id": acc, "full_name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(client, ws, acc, text):
    r = client.post(f"{ws}/accounts/{acc}/documents", files={"file": ("m.txt", text.encode())})
    assert r.status_code == 201, r.text
    return r.json()


def accepted_pair(client, ws):
    acc = account(client, ws)
    x = person(client, ws, acc, "Xavier Xu")
    y = person(client, ws, acc, "Yvonne Yu")
    upload(client, ws, acc, "Xavier Xu: I report to Yvonne Yu.\n")
    propose(client, ws, acc, ["meeting"])
    p = proposals(client, ws, acc)[0]
    assert client.post(f"{ws}/org-proposals/{p['id']}/accept", json={}).status_code == 200
    return acc, x, y


# --- SR12-01 ---------------------------------------------------------------------------------
def test_erase_manager_of_an_accepted_proposal(client, ws, db_session):
    acc, x, y = accepted_pair(client, ws)
    assert client.delete(f"{ws}/contacts/{y}").status_code == 204
    db_session.expire_all()
    cx = db_session.get(Contact, uuid.UUID(x))
    assert cx.reports_to_id is None and cx.reports_to_proposal_id is None
    assert db_session.scalars(select(OrgProposal)).all() == []


def test_erase_subordinate_and_contact_with_pending_proposals(client, ws, db_session, team):  # noqa: F811
    propose(client, ws, team["acc"], ["rule"])
    assert proposals(client, ws, team["acc"])
    assert client.delete(f"{ws}/contacts/{team['mgr']}").status_code == 204
    left = proposals(client, ws, team["acc"])
    assert all(
        team["mgr"] not in (p["contact"]["id"], (p["manager"] or {}).get("id")) for p in left
    )
    assert client.delete(f"{ws}/contacts/{team['rep']}").status_code == 204


def test_erase_candidate_of_an_ambiguous_proposal(client, ws, db_session, team):  # noqa: F811
    mk_contact(client, db_session, ws, team["acc"], "Tom Manager", "sales", "manager")
    propose(client, ws, team["acc"], ["rule"])
    assert client.delete(f"{ws}/contacts/{team['mgr']}").status_code == 204
    for p in db_session.scalars(select(OrgProposal)):
        assert team["mgr"] not in (p.candidates or [])


# --- SR12-03 ---------------------------------------------------------------------------------
def test_erasure_redacts_transcripts_without_moving_offsets(client, ws, db_session):
    acc = account(client, ws)
    marie = person(client, ws, acc, "Marie Dupont")
    person(client, ws, acc, "Bob Bobby")
    person(client, ws, acc, "Zoe Zed")
    text = (
        "Marie Dupont: Mon code secret est 1234. Bob Bobby is against it.\n"
        "Bob Bobby: I report to Zoe Zed, and Marie Dupont agrees. Dupont Marie nods.\n"
        "Zoe Zed: Merci Marie Dupont."
    )
    doc = upload(client, ws, acc, text)
    propose(client, ws, acc, ["meeting"])
    assert any("Marie" in p["evidence"].get("excerpt", "") for p in proposals(client, ws, acc))
    before = db_session.get(Document, uuid.UUID(doc["id"])).text
    assert client.delete(f"{ws}/contacts/{marie}").status_code == 204
    db_session.expire_all()
    d = db_session.get(Document, uuid.UUID(doc["id"]))
    assert len(d.text) == len(before) and d.n_chars == len(before)
    assert "Marie" not in d.text and "Dupont" not in d.text and "1234" not in d.text
    assert "[erased]" in d.text and "[name]" in d.text
    assert "Bob Bobby: I report to Zoe Zed" in d.text and "Zoe Zed: Merci" in d.text
    chunks = db_session.scalars(
        select(DocumentChunk).where(DocumentChunk.document_id == d.id)
    ).all()
    assert chunks and all(d.text[c.char_start : c.char_end] == c.text for c in chunks)
    assert all("Marie" not in (c.speaker or "") and "secret" not in c.text for c in chunks)
    assert "[erased]" in {c.speaker for c in chunks}
    # the API no longer returns the name or the words
    body = client.get(f"{ws}/documents/{d.id}").text
    assert "Marie" not in body and "secret" not in body
    # excerpts still match the redacted text; none quotes the name
    for p in db_session.scalars(select(OrgProposal)):
        ev = p.evidence
        if "excerpt" in ev:
            assert d.text[ev["char_start"] : ev["char_end"]] == ev["excerpt"]
            assert "Marie" not in ev["excerpt"] and "Dupont" not in ev["excerpt"]


def test_erasure_redacts_excerpt_of_other_contacts_proposal(client, ws, db_session):
    acc = account(client, ws)
    marie = person(client, ws, acc, "Marie Dupont")
    person(client, ws, acc, "Bob Bobby")
    person(client, ws, acc, "Zoe Zed")
    upload(client, ws, acc, "Bob Bobby: I report to Zoe Zed, and Marie Dupont agrees.\n")
    propose(client, ws, acc, ["meeting"])
    p = proposals(client, ws, acc)[0]
    assert "Marie Dupont" in p["evidence"]["excerpt"]
    assert client.delete(f"{ws}/contacts/{marie}").status_code == 204
    p2 = proposals(client, ws, acc)[0]
    assert p2["evidence"]["excerpt"] == p["evidence"]["excerpt"].replace(
        "Marie Dupont", "[name]      "
    )
    assert len(p2["evidence"]["excerpt"]) == len(p["evidence"]["excerpt"])


# --- lows --------------------------------------------------------------------------------------
def test_stale_accept_needs_force(client, ws, team):  # noqa: F811
    propose(client, ws, team["acc"], ["rule"])
    p = by_contact(proposals(client, ws, team["acc"]), team["rep"])[0]
    assert p["manager"]["id"] == team["mgr"]
    r = client.put(f"{ws}/contacts/{team['rep']}/reports-to", json={"manager_id": team["ceo"]})
    assert r.status_code == 200
    url = f"{ws}/org-proposals/{p['id']}/accept"
    assert client.post(url, json={}).status_code == 409
    chart = {
        n["id"]: n for n in client.get(f"{ws}/accounts/{team['acc']}/org-chart").json()["nodes"]
    }
    assert chart[team["rep"]]["reports_to_id"] == team["ceo"]
    ok = client.post(url, json={"force": True})
    assert ok.status_code == 200 and ok.json()["manager"]["id"] == team["mgr"]


def test_rejected_ambiguous_is_not_reproposed(client, ws, db_session, team):  # noqa: F811
    mk_contact(client, db_session, ws, team["acc"], "Tom Manager", "sales", "manager")
    assert propose(client, ws, team["acc"], ["rule"])["ambiguous"] == 1
    amb = by_contact(proposals(client, ws, team["acc"]), team["rep"])[0]
    assert client.post(f"{ws}/org-proposals/{amb['id']}/reject", json={}).status_code == 200
    assert propose(client, ws, team["acc"], ["rule"])["ambiguous"] == 0
    # a different candidate set is a new question
    mk_contact(client, db_session, ws, team["acc"], "Una Manager", "sales", "manager")
    assert propose(client, ws, team["acc"], ["rule"])["ambiguous"] == 1


def test_chunk_cap_is_a_clear_422(client, ws):
    acc = account(client, ws)
    text = "\n".join(f"s{i % 2}: x" for i in range(5_001))
    r = client.post(f"{ws}/accounts/{acc}/documents", files={"file": ("m.txt", text.encode())})
    assert r.status_code == 422 and "speaker turns" in r.text
    ok = "\n".join(f"s{i % 2}: x" for i in range(5_000))
    assert (
        client.post(f"{ws}/accounts/{acc}/documents", files={"file": ("m.txt", ok.encode())})
    ).status_code == 201


# --- title AI budget -------------------------------------------------------------------------
KEY = "AIzaSyTESTKEY-0123456789abcdefghij"


def _ai_factory(app, calls, fail):
    def factory(provider, *, api_key, model, settings, usage):
        llm = FakeLLM(usage=usage)

        def h(s, u):
            calls.append(u)
            if fail:
                raise LLMError("down")
            return TitleAnswer(function="hr", seniority="manager", confidence="low")

        llm.register(TitleAnswer, h)
        return llm

    app.dependency_overrides[get_title_factory] = lambda: factory


def _titles_ws(client, ws):
    acc = account(client, ws)
    assert (
        client.put(
            f"{ws}/ai", json={"provider": "gemini", "model": "m", "api_key": KEY}
        ).status_code
        == 200
    )
    return acc


def test_title_failures_are_not_retried(client, ws, app):
    title_service.reset_ai_limits()
    calls: list[str] = []
    _ai_factory(app, calls, fail=True)
    acc = _titles_ws(client, ws)
    client.post(f"{ws}/contacts", json={"account_id": acc, "full_name": "A B", "title": "Zorglub"})
    for _ in range(3):
        r = client.post(f"{ws}/titles/normalize", json={})
        assert r.status_code == 200
    assert len(calls) == 1


def test_title_daily_cap(client, ws, app, api_settings, monkeypatch):
    title_service.reset_ai_limits()
    monkeypatch.setattr(api_settings, "titles_max_llm_calls_per_day", 2)
    calls: list[str] = []
    _ai_factory(app, calls, fail=False)
    acc = _titles_ws(client, ws)
    for i, t in enumerate(["Zorglub", "Quux", "Frobnicate", "Wibble"]):
        client.post(f"{ws}/contacts", json={"account_id": acc, "full_name": f"P{i} Q", "title": t})
    first = client.post(f"{ws}/titles/normalize", json={}).json()
    assert first["llm_calls"] == 2
    second = client.post(f"{ws}/titles/normalize", json={}).json()
    assert second["llm_calls"] == 0 and len(calls) == 2
    flags = [i["flag"] for i in client.get(f"{ws}/titles/review").json()]
    assert "unknown title (AI call limit reached)" in flags
    title_service.reset_ai_limits()


# --- deleting a transcript drops the quotes taken from it ------------------------------------
def test_delete_transcript_forgets_its_quotes(client, ws):
    acc = account(client, ws)
    for name in ("Xavier Xu", "Yvonne Yu", "Zoe Zed"):
        person(client, ws, acc, name)
    first = upload(client, ws, acc, "Xavier Xu: I report to Yvonne Yu.\n")
    second = upload(client, ws, acc, "Zoe Zed: I report to Yvonne Yu.\n")
    propose(client, ws, acc, ["meeting"])
    ps = {p["contact"]["full_name"]: p for p in proposals(client, ws, acc)}
    accept = client.post(f"{ws}/org-proposals/{ps['Xavier Xu']['id']}/accept", json={})
    assert accept.status_code == 200
    assert "Yvonne Yu" in ps["Zoe Zed"]["evidence"]["excerpt"]
    for doc in (first, second):
        assert client.delete(f"{ws}/documents/{doc['id']}").status_code == 204
    left = proposals(client, ws, acc)
    assert [p["contact"]["full_name"] for p in left] == ["Xavier Xu"]  # the open one is gone
    ev = left[0]["evidence"]
    assert left[0]["status"] == "accepted" and ev["document_deleted"] is True
    assert not {"excerpt", "speaker", "char_start", "char_end"} & set(ev)
    assert "Yvonne Yu" not in str(ev)
