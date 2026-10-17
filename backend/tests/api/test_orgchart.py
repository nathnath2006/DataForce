"""Org-chart proposals through the HTTP API and the services."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import Contact, Document, DocumentChunk

pytestmark = pytest.mark.integration


@pytest.fixture
def ws(client: TestClient) -> str:
    assert client.post("/api/workspaces", json={"slug": "o1", "name": "O1"}).status_code == 201
    return "/api/w/o1"


@pytest.fixture
def other(client: TestClient) -> str:
    assert client.post("/api/workspaces", json={"slug": "o2", "name": "O2"}).status_code == 201
    return "/api/w/o2"


def mk_account(client, ws, name="Acme") -> str:
    r = client.post(f"{ws}/accounts", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def mk_contact(client, db: Session, ws, acc, name, function=None, seniority=None, **kw) -> str:
    r = client.post(f"{ws}/contacts", json={"account_id": acc, "full_name": name, **kw})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    c = db.get(Contact, uuid.UUID(cid))
    c.title, c.title_function, c.title_seniority = name, function, seniority
    db.flush()
    return cid


@pytest.fixture
def team(client, ws, db_session):
    acc = mk_account(client, ws)
    ceo = mk_contact(client, db_session, ws, acc, "Ceo Boss", "executive", "c_level")
    cfo = mk_contact(client, db_session, ws, acc, "Cfo Money", "finance", "c_level")
    mgr = mk_contact(client, db_session, ws, acc, "Sam Manager", "sales", "manager")
    rep = mk_contact(client, db_session, ws, acc, "Rita Rep", "sales", "individual")
    return {"acc": acc, "ceo": ceo, "cfo": cfo, "mgr": mgr, "rep": rep}


def propose(client, ws, acc, origins=("rule", "meeting")):
    r = client.post(f"{ws}/orgchart/propose", json={"account_id": acc, "origins": list(origins)})
    assert r.status_code == 200, r.text
    return r.json()


def proposals(client, ws, acc, status=None):
    q = f"?status={status}" if status else ""
    r = client.get(f"{ws}/accounts/{acc}/org-proposals{q}")
    assert r.status_code == 200, r.text
    return r.json()


def by_contact(rows, cid):
    return [p for p in rows if p["contact"]["id"] == cid]


def add_doc(
    db: Session, ws, acc, contacts: dict[str, str], lines: list[tuple[str, str | None, str]]
):
    """lines: (speaker, contact key, text). Inserts a Document and its chunks directly."""
    slug = ws.rsplit("/", 1)[1]
    from sqlalchemy import select

    from app.db.models import Workspace

    ws_id = db.scalar(select(Workspace.id).where(Workspace.slug == slug))
    body, spans = "", []
    for speaker, _, t in lines:
        prefix = f"{speaker}: "
        start = len(body) + len(prefix)
        body += prefix + t + "\n"
        spans.append((start, start + len(t)))
    doc = Document(
        workspace_id=ws_id,
        account_id=uuid.UUID(acc),
        title="m",
        sha256="0" * 64,
        size_bytes=len(body),
        text=body,
        n_chars=len(body),
    )
    db.add(doc)
    db.flush()
    for i, ((speaker, key, t), (s, e)) in enumerate(zip(lines, spans, strict=True)):
        db.add(
            DocumentChunk(
                workspace_id=ws_id,
                document_id=doc.id,
                seq=i,
                speaker=speaker,
                contact_id=uuid.UUID(contacts[key]) if key else None,
                char_start=s,
                char_end=e,
                text=t,
            )
        )
    db.flush()
    return doc


def test_rules_run_and_listing(client, ws, team):
    out = propose(client, ws, team["acc"], ["rule"])
    assert out["created"] == 2 and out["by_kind"] == {"reports_to": 2} and out["ambiguous"] == 0
    rows = proposals(client, ws, team["acc"])
    cfo = by_contact(rows, team["cfo"])[0]
    assert cfo["rule"] == "c_level_to_ceo" and cfo["manager"]["id"] == team["ceo"]
    assert cfo["status"] == "proposed" and cfo["evidence"]["explanation"]
    rep = by_contact(rows, team["rep"])[0]
    assert rep["manager"]["id"] == team["mgr"] and rep["rule"] == "next_level_in_function"
    assert len(proposals(client, ws, team["acc"], "accepted")) == 0
    assert client.get(f"{ws}/accounts/{team['acc']}/org-proposals?status=bogus").status_code == 422


def test_rerun_replaces_open_but_keeps_decided(client, ws, team):
    propose(client, ws, team["acc"], ["rule"])
    cfo = by_contact(proposals(client, ws, team["acc"]), team["cfo"])[0]
    assert client.post(f"{ws}/org-proposals/{cfo['id']}/accept", json={}).status_code == 200
    out = propose(client, ws, team["acc"], ["rule"])
    assert out["created"] == 1  # the CFO now has a link
    rows = proposals(client, ws, team["acc"])
    assert len(rows) == 2
    assert {p["status"] for p in rows} == {"accepted", "proposed"}


def test_ambiguity(client, ws, db_session, team):
    mgr2 = mk_contact(client, db_session, ws, team["acc"], "Tom Manager", "sales", "manager")
    out = propose(client, ws, team["acc"], ["rule"])
    assert out["ambiguous"] == 1
    amb = by_contact(proposals(client, ws, team["acc"]), team["rep"])[0]
    assert amb["status"] == "ambiguous" and amb["manager"] is None
    assert {c["id"] for c in amb["candidates"]} == {team["mgr"], mgr2}
    url = f"{ws}/org-proposals/{amb['id']}/accept"
    assert client.post(url, json={}).status_code == 422  # must pick
    assert client.post(url, json={"manager_id": team["ceo"]}).status_code == 422  # not a candidate
    ok = client.post(url, json={"manager_id": mgr2})
    assert ok.status_code == 200 and ok.json()["manager"]["id"] == mgr2
    chart = client.get(f"{ws}/accounts/{team['acc']}/org-chart").json()["nodes"]
    node = next(n for n in chart if n["id"] == team["rep"])
    assert node["reports_to_id"] == mgr2 and node["link_origin"] == "rule"
    assert node["link_proposal_id"] == amb["id"]


def test_accept_reject_and_chart_fields(client, ws, team):
    propose(client, ws, team["acc"], ["rule"])
    rows = proposals(client, ws, team["acc"])
    cfo = by_contact(rows, team["cfo"])[0]
    rep = by_contact(rows, team["rep"])[0]
    acc_resp = client.post(f"{ws}/org-proposals/{cfo['id']}/accept")
    assert acc_resp.status_code == 200 and acc_resp.json()["status"] == "accepted"
    assert acc_resp.json()["decided_at"]
    rej = client.post(f"{ws}/org-proposals/{rep['id']}/reject", json={})
    assert rej.json()["status"] == "rejected"
    # decided proposals cannot be decided again
    assert client.post(f"{ws}/org-proposals/{cfo['id']}/reject", json={}).status_code == 422
    assert client.post(f"{ws}/org-proposals/{rep['id']}/accept", json={}).status_code == 422
    nodes = {
        n["id"]: n for n in client.get(f"{ws}/accounts/{team['acc']}/org-chart").json()["nodes"]
    }
    assert nodes[team["cfo"]]["link_origin"] == "rule"
    assert nodes[team["cfo"]]["link_proposal_id"] == cfo["id"]
    assert nodes[team["cfo"]]["title_function"] == "finance"
    assert nodes[team["cfo"]]["title_seniority"] == "c_level"
    assert nodes[team["rep"]]["link_origin"] is None and nodes[team["rep"]]["signals"] == []
    assert client.post(f"{ws}/org-proposals/{cfo['id']}/accept", json={"x": 1}).status_code == 422


def test_no_reproposal_after_rejection(client, ws, team):
    propose(client, ws, team["acc"], ["rule"])
    rep = by_contact(proposals(client, ws, team["acc"]), team["rep"])[0]
    client.post(f"{ws}/org-proposals/{rep['id']}/reject", json={})
    propose(client, ws, team["acc"], ["rule"])
    rows = by_contact(proposals(client, ws, team["acc"]), team["rep"])
    assert [p["status"] for p in rows] == ["rejected"]


def test_manual_link_is_never_overwritten_and_clears_proposal(client, ws, team):
    propose(client, ws, team["acc"], ["rule"])
    rep = by_contact(proposals(client, ws, team["acc"]), team["rep"])[0]
    client.post(f"{ws}/org-proposals/{rep['id']}/accept", json={})
    # a manual change clears reports_to_proposal_id
    assert (
        client.put(
            f"{ws}/contacts/{team['rep']}/reports-to", json={"manager_id": team["ceo"]}
        ).status_code
        == 200
    )
    nodes = {
        n["id"]: n for n in client.get(f"{ws}/accounts/{team['acc']}/org-chart").json()["nodes"]
    }
    assert nodes[team["rep"]]["link_origin"] == "manual"
    assert nodes[team["rep"]]["link_proposal_id"] is None
    out = propose(client, ws, team["acc"], ["rule"])
    assert out["created"] == 1  # only the CFO
    chart = client.get(f"{ws}/accounts/{team['acc']}/org-chart").json()["nodes"]
    assert next(n for n in chart if n["id"] == team["rep"])["reports_to_id"] == team["ceo"]
    assert not by_contact(proposals(client, ws, team["acc"], "proposed"), team["rep"])


def test_no_cycle_and_no_cross_account(client, ws, db_session, team):
    # the manager is (manually) below the rep: proposing rep -> manager would loop
    client.put(f"{ws}/contacts/{team['mgr']}/reports-to", json={"manager_id": team["rep"]})
    propose(client, ws, team["acc"], ["rule"])
    assert not by_contact(proposals(client, ws, team["acc"]), team["rep"])
    acc2 = mk_account(client, ws, "Other")
    mk_contact(client, db_session, ws, acc2, "Far Manager", "sales", "manager")
    propose(client, ws, team["acc"], ["rule"])
    for p in proposals(client, ws, team["acc"]):
        assert p["manager"] is None or p["manager"]["full_name"] != "Far Manager"
    assert proposals(client, ws, acc2) == []


def test_meeting_proposals_with_evidence(client, ws, db_session, team):
    c = team
    add_doc(
        db_session,
        ws,
        c["acc"],
        c,
        [
            ("Rita", "rep", "Hello. I report to Ceo Boss! Also I'll push this internally."),
            ("Rita", "rep", "Cfo is against the plan. Je reporte à personne."),
            ("Rita", "rep", "C'est Sam qui décide."),
            ("Stranger", None, "I report to Sam."),
        ],
    )
    out = propose(client, ws, c["acc"], ["meeting"])
    assert out["by_kind"] == {"reports_to": 1, "champion": 1, "blocker": 1, "decision_maker": 1}
    rows = proposals(client, ws, c["acc"])
    rt = next(p for p in rows if p["kind"] == "reports_to")
    assert rt["origin"] == "meeting" and rt["contact"]["id"] == c["rep"]
    assert rt["manager"]["id"] == c["ceo"]
    ev = rt["evidence"]
    doc = db_session.get(Document, uuid.UUID(ev["document_id"]))
    assert doc.text[ev["char_start"] : ev["char_end"]] == ev[
        "excerpt"
    ] == "I report to Ceo Boss!" or ev["excerpt"].endswith("I report to Ceo Boss!")
    assert ev["speaker"] == "Rita" and ev["chunk_id"]
    # signals: accepting only changes the status
    ch = next(p for p in rows if p["kind"] == "champion")
    assert client.post(f"{ws}/org-proposals/{ch['id']}/accept", json={}).status_code == 200
    assert client.post(f"{ws}/org-proposals/{ch['id']}/accept", json={}).status_code == 422
    nodes = {n["id"]: n for n in client.get(f"{ws}/accounts/{c['acc']}/org-chart").json()["nodes"]}
    assert nodes[c["rep"]]["signals"] == ["champion"]
    assert nodes[c["rep"]]["reports_to_id"] is None


def test_contradicts_current_link(client, ws, db_session, team):
    c = team
    client.put(f"{ws}/contacts/{c['rep']}/reports-to", json={"manager_id": c["mgr"]})
    add_doc(db_session, ws, c["acc"], c, [("Rita", "rep", "I report to Ceo Boss.")])
    propose(client, ws, c["acc"], ["meeting"])
    p = by_contact(proposals(client, ws, c["acc"]), c["rep"])[0]
    assert p["rule"] == "contradicts_current_link" and p["manager"]["id"] == c["ceo"]
    # the manual link is untouched until a user accepts
    nodes = {n["id"]: n for n in client.get(f"{ws}/accounts/{c['acc']}/org-chart").json()["nodes"]}
    assert (
        nodes[c["rep"]]["reports_to_id"] == c["mgr"] and nodes[c["rep"]]["link_origin"] == "manual"
    )
    # a statement matching the current link proposes nothing
    client.put(f"{ws}/contacts/{c['rep']}/reports-to", json={"manager_id": c["ceo"]})
    propose(client, ws, c["acc"], ["meeting"])
    assert proposals(client, ws, c["acc"]) == []


def test_meeting_rerun_keeps_rejected_blocked(client, ws, db_session, team):
    c = team
    add_doc(db_session, ws, c["acc"], c, [("Rita", "rep", "I'll champion it.")])
    propose(client, ws, c["acc"], ["meeting"])
    p = proposals(client, ws, c["acc"])[0]
    client.post(f"{ws}/org-proposals/{p['id']}/reject", json={})
    out = propose(client, ws, c["acc"], ["meeting"])
    assert out["created"] == 0


def test_accept_takes_the_account_lock_and_refuses_cycles(client, ws, db_session, team):
    propose(client, ws, team["acc"], ["rule"])
    rep = by_contact(proposals(client, ws, team["acc"]), team["rep"])[0]
    # the manager now reports to the rep: accepting would close a loop
    client.put(f"{ws}/contacts/{team['mgr']}/reports-to", json={"manager_id": team["rep"]})
    assert client.post(f"{ws}/org-proposals/{rep['id']}/accept", json={}).status_code == 422
    db_session.execute(text("SELECT 1"))
    # the service takes the advisory lock before re-reading the proposal status
    from sqlalchemy import select

    from app.db.models import Workspace
    from app.services import org_proposals

    ws_id = db_session.scalar(select(Workspace.id).where(Workspace.slug == "o1"))
    client.put(f"{ws}/contacts/{team['mgr']}/reports-to", json={"manager_id": None})
    org_proposals.accept(db_session, ws_id, uuid.UUID(rep["id"]))
    held = db_session.execute(
        text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()")
    ).scalar_one()
    assert held >= 1
    with pytest.raises(Exception, match="already accepted"):
        org_proposals.accept(db_session, ws_id, uuid.UUID(rep["id"]))


def test_workspace_isolation(client, ws, other, team):
    propose(client, ws, team["acc"], ["rule"])
    row = proposals(client, ws, team["acc"])[0]
    assert client.get(f"{other}/accounts/{team['acc']}/org-proposals").status_code == 404
    assert client.post(f"{other}/org-proposals/{row['id']}/accept", json={}).status_code == 404
    assert client.post(f"{other}/org-proposals/{row['id']}/reject", json={}).status_code == 404
    assert (
        client.post(
            f"{other}/orgchart/propose", json={"account_id": team["acc"], "origins": ["rule"]}
        ).status_code
        == 404
    )
    # whole-workspace run in the other workspace creates nothing
    out = client.post(f"{other}/orgchart/propose", json={"account_id": None, "origins": ["rule"]})
    assert out.json()["created"] == 0
