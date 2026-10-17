"""Transcript import and endpoints (fake data only, no network)."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfWriter

from tests.api.test_crm import mk_account, mk_contact, mk_deal

pytestmark = pytest.mark.integration


@pytest.fixture
def ws(client):
    assert client.post("/api/workspaces", json={"slug": "t1", "name": "T1"}).status_code == 201
    return "/api/w/t1"


@pytest.fixture
def other(client):
    assert client.post("/api/workspaces", json={"slug": "t2", "name": "T2"}).status_code == 201
    return "/api/w/t2"


TEXT = (
    "**Marie Dupont**: Bonjour, le prix est trop cher pour notre budget.\n"
    "Rep Jean: Je comprends, nous pouvons faire une remise.\n"
    "Inconnu: ok\n"
)


def up(client, ws, acc, name="m.md", data=TEXT.encode(), **form):
    return client.post(f"{ws}/accounts/{acc}/documents", files={"file": (name, data)}, data=form)


def test_upload_read_delete_and_matching(client, ws, other):
    acc = mk_account(client, ws)
    c = mk_contact(client, ws, acc["id"], "Marie Dupont")
    u = client.post(f"{ws}/users", json={"display_name": "Rep Jean"})
    deal = mk_deal(client, ws, acc["id"])
    r = up(client, ws, acc["id"], title="Kickoff", meeting_date="2026-02-03", deal_id=deal["id"])
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["title"] == "Kickoff" and d["n_chunks"] == 3 and d["language"] == "fr"
    assert d["account_name"] == "Acme" and d["deal_id"] == deal["id"]
    sp = {s["name"]: s for s in d["speakers"]}
    assert sp["Marie Dupont"]["contact_id"] == c["id"]
    if u.status_code == 201:
        assert sp["Rep Jean"]["user_id"] == u.json()["id"]
    assert sp["Inconnu"]["contact_id"] is None
    detail = client.get(f"{ws}/documents/{d['id']}").json()
    assert "**" not in detail["text"]
    for ch in detail["chunks"]:
        assert detail["text"][ch["char_start"] : ch["char_end"]]
    assert client.get(f"{ws}/accounts/{acc['id']}/documents").json()[0]["id"] == d["id"]
    page = client.get(f"{ws}/documents?limit=1").json()
    assert page["total"] == 1 and len(page["items"]) == 1
    assert client.get("/api/w/t2/documents").json()["total"] == 0
    assert client.get(f"/api/w/t2/documents/{d['id']}").status_code == 404
    assert client.delete(f"/api/w/t2/documents/{d['id']}").status_code == 404
    assert client.delete(f"{ws}/documents/{d['id']}").status_code == 204
    assert client.get(f"{ws}/documents/{d['id']}").status_code == 404


def test_refusals(client, ws, other):
    acc = mk_account(client, ws)
    other_acc = mk_account(client, other, "Foreign")
    deal2 = mk_deal(client, ws, mk_account(client, ws, "B")["id"])
    assert up(client, ws, acc["id"], deal_id=deal2["id"]).status_code == 422
    assert up(client, ws, other_acc["id"]).status_code == 404
    assert up(client, ws, acc["id"], name="x.exe").status_code == 422
    assert up(client, ws, acc["id"], name="x.pdf", data=b"nope").status_code == 422
    w = PdfWriter()
    w.add_blank_page(100, 100)
    w.encrypt("pw")
    buf = io.BytesIO()
    w.write(buf)
    assert up(client, ws, acc["id"], name="x.pdf", data=buf.getvalue()).status_code == 422
    assert up(client, ws, acc["id"], name="e.txt", data=b"").status_code == 422
    big = b"Marie: " + b"a" * (5 * 1024 * 1024)
    assert up(client, ws, acc["id"], name="b.txt", data=big).status_code == 422


def test_latin1_and_company_listing(client, ws, db_session):
    from sqlalchemy import select

    from app.db.models import Account, Company, Workspace

    acc = mk_account(client, ws)
    ws_id = db_session.scalar(select(Workspace.id).where(Workspace.slug == "t1"))
    co = Company(workspace_id=ws_id, name="Acme Group")
    db_session.add(co)
    db_session.flush()
    db_session.get(Account, __import__("uuid").UUID(acc["id"])).company_id = co.id
    db_session.flush()
    r = up(client, ws, acc["id"], name="l.txt", data="Marie: très cher, le café".encode("latin-1"))
    assert r.status_code == 201
    text = client.get(f"{ws}/documents/{r.json()['id']}").json()["text"]
    assert "très" in text
    assert len(client.get(f"{ws}/companies/{co.id}/documents").json()) == 1


def test_erase_contact_keeps_chunks_and_account_deletes_documents(client, ws, db_session):
    acc = mk_account(client, ws)
    c = mk_contact(client, ws, acc["id"], "Marie Dupont")
    d = up(client, ws, acc["id"]).json()
    assert client.delete(f"{ws}/contacts/{c['id']}").status_code == 204
    detail = client.get(f"{ws}/documents/{d['id']}").json()
    assert len(detail["chunks"]) == 3 and all(ch["contact_id"] is None for ch in detail["chunks"])
    assert client.delete(f"{ws}/accounts/{acc['id']}").status_code == 204
    assert client.get(f"{ws}/documents/{d['id']}").status_code == 404


def test_add_document_signature(client, ws, db_session):
    import uuid

    from sqlalchemy import select

    from app.db.models import Workspace
    from app.services.documents import add_document

    acc = mk_account(client, ws)
    ws_id = db_session.scalar(select(Workspace.id).where(Workspace.slug == "t1"))
    doc = add_document(
        db_session,
        ws_id,
        account_id=uuid.UUID(acc["id"]),
        title="T",
        text="Paul: salut\nAnna: hello",
        source="demo",
    )
    assert doc.source == "demo" and doc.n_chars == len(doc.text)
