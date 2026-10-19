"""Theme run endpoints and the three flows tables (fake provider only)."""

from __future__ import annotations

import random

import pytest

from app.api.routes.ai import get_chat_factory
from app.flows.sources.crm import CRM_COLUMNS, load_crm_table
from app.llm.fake import FakeLLM
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


KEY = "AIzaSyTESTKEY-0123456789abcdefghij"
VOCABS = {  # neutral words: none belongs to the known-theme lexicon
    "garden": "orchid lantern marble velvet cobalt meadow harvest".split(),
    "travel": "harbor compass voyage glacier lagoon summit canyon".split(),
    "music": "violin cadence chorus melody tempo octave rhythm".split(),
}


def transcript(words, seed):
    rnd = random.Random(seed)
    return "\n".join(f"Marie Dupont: {' '.join(rnd.choices(words, k=6))} merci" for _ in range(8))


@pytest.fixture
def world(client, ws):
    acc = mk_account(client, ws)
    mk_contact(client, ws, acc["id"], "Marie Dupont")
    deals = {}
    n = 0
    for name, words in VOCABS.items():
        deal = mk_deal(client, ws, acc["id"], f"Deal {name}")
        deals[name] = deal
        for _ in range(3):
            n += 1
            r = client.post(
                f"{ws}/accounts/{acc['id']}/documents",
                files={"file": (f"{name}{n}.txt", transcript(words, n).encode())},
                data={"deal_id": deal["id"]},
            )
            assert r.status_code == 201, r.text
    return acc, deals


@pytest.fixture
def fake(app):
    box = {}

    def factory(provider, *, api_key, model, settings, usage):
        box["llm"] = FakeLLM(usage=usage)
        return box["llm"]

    app.dependency_overrides[get_chat_factory] = lambda: factory
    return box


def test_run_keywords_and_latest(client, ws, world):
    assert client.get(f"{ws}/themes/latest").status_code == 404
    r = client.post(f"{ws}/themes/run", json={"k": 6, "use_ai": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["k"] == 6 and body["n_chunks_used"] == 72 and len(body["themes"]) == 3
    t = body["themes"][0]
    assert body["known_themes"] == [] and t["origin"] == "discovered"
    assert t["named_by"] == "keywords" and t["status"] == "exploratory" and len(t["excerpts"]) == 3
    assert t["n_chunks"] >= 3 and t["n_accounts"] == 1
    assert client.get(f"{ws}/themes/latest").json()["themes"][0]["label"] == t["label"]
    docs = client.get(f"{ws}/documents").json()["items"]
    assert all(d["theme_labels"] for d in docs)
    again = client.post(f"{ws}/themes/run", json={"k": 6, "use_ai": False}).json()
    assert [x["top_terms"] for x in again["themes"]] == [x["top_terms"] for x in body["themes"]]
    assert client.post(f"{ws}/themes/run", json={"k": 1}).status_code == 422
    assert client.post(f"{ws}/themes/run", json={"zzz": 1}).status_code == 422


def test_run_with_ai_fake_and_isolation(client, ws, other, world, fake):
    client.put(f"{ws}/ai", json={"provider": "gemini", "model": "m", "api_key": KEY})
    r = client.post(f"{ws}/themes/run", json={"k": 6})
    assert r.status_code == 200, r.text
    assert {t["named_by"] for t in r.json()["themes"]} == {"llm"}
    assert client.get("/api/w/t2/themes/latest").status_code == 404
    assert client.post("/api/w/t2/themes/run", json={}).status_code == 422  # no text


def test_not_enough_text(client, ws):
    assert client.post(f"{ws}/themes/run", json={}).status_code == 422


def test_flows_tables(client, ws, world, db_session):
    from sqlalchemy import select

    from app.db.models import Workspace

    ws_id = db_session.scalar(select(Workspace.id).where(Workspace.slug == "t1"))
    for table in ("meetings", "meeting_themes", "deal_theme_flags"):
        df = load_crm_table(db_session, ws_id, table, 1000)
        assert list(df.columns) == [c for c, _ in CRM_COLUMNS[table]]
    assert len(load_crm_table(db_session, ws_id, "meetings", 1000)) == 9
    assert load_crm_table(db_session, ws_id, "deal_theme_flags", 1000).empty
    client.post(f"{ws}/themes/run", json={"k": 6, "use_ai": False})
    mt = load_crm_table(db_session, ws_id, "meeting_themes", 1000)
    assert len(mt) >= 9 and (mt["n_chunks"] > 0).all()
    flags = load_crm_table(db_session, ws_id, "deal_theme_flags", 1000)
    assert len(flags) == 9 and flags["has_meeting"].all()
    assert flags["mentioned"].isin([True, False]).all()
    assert flags.groupby("deal_id")["mentioned"].sum().ge(1).all()
    # A deal nobody met about: "mentioned" is unknown (None), never False.
    from datetime import date

    from app.db.models import Account
    from app.domain.schemas import DealIn
    from app.services import deals

    acc = db_session.scalar(select(Account.id).where(Account.workspace_id == ws_id).limit(1))
    deals.create_deal(
        db_session, ws_id, DealIn(account_id=acc, name="no meeting", created_on=date(2026, 1, 5))
    )
    flags = load_crm_table(db_session, ws_id, "deal_theme_flags", 1000)
    lonely = flags[flags["deal_name"] == "no meeting"]
    assert len(lonely) == 3 and not lonely["has_meeting"].any()
    assert lonely["mentioned"].isna().all()
    contacts = load_crm_table(db_session, ws_id, "contacts", 1000)
    assert {"title_function", "title_seniority"} <= set(contacts.columns)


def test_known_themes_labels_and_naming_only_for_other_topics(client, ws, world, fake):
    acc, _ = world
    deal = mk_deal(client, ws, acc["id"], "Deal mixed")
    for i in range(3):
        text = (
            "Marie Dupont: Le prix est trop cher, nous voulons une remise.\n"
            f"Marie Dupont: Notre RGPD et la sécurité comptent. Variation {i}.\n"
        )
        r = client.post(
            f"{ws}/accounts/{acc['id']}/documents",
            files={"file": (f"mixed{i}.txt", text.encode())},
            data={"deal_id": deal["id"]},
        )
        assert r.status_code == 201, r.text
    client.put(f"{ws}/ai", json={"provider": "gemini", "model": "m", "api_key": KEY})
    body = client.post(f"{ws}/themes/run", json={"k": 6}).json()
    assert set(body["known_themes"]) == {"price", "security"}
    by_origin = {}
    for t in body["themes"]:
        by_origin.setdefault(t["origin"], []).append(t)
    assert {t["label"] for t in by_origin["known"]} == {"Price", "Security and compliance"}
    assert {t["named_by"] for t in by_origin["known"]} == {"lexicon"}
    assert {t["named_by"] for t in by_origin["discovered"]} == {"llm"}
    assert {t["kind"] for t in by_origin["known"]} == {"objection"}
    latest = client.get(f"{ws}/themes/latest").json()
    assert set(latest["known_themes"]) == {"price", "security"}


def test_themes_of_run_matches_per_theme_reference(client, ws, world, db_session):
    from sqlalchemy import select

    from app.db.models import Account, Document, DocumentChunk, ThemeAssignment
    from app.services import themes as svc
    from app.themes import discover as disc

    body = client.post(f"{ws}/themes/run", json={"k": 6, "use_ai": False}).json()
    run = svc.latest_run(db_session, svc_ws_id(db_session))
    views = svc.themes_of_run(db_session, run.workspace_id, run.id)
    assert len(views) == len(body["themes"])
    for v in views:
        rows = db_session.execute(
            select(DocumentChunk, Document, Account.name)
            .select_from(ThemeAssignment)
            .join(DocumentChunk, DocumentChunk.id == ThemeAssignment.chunk_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(Account, Account.id == Document.account_id)
            .where(ThemeAssignment.theme_id == v.theme.id)
            .order_by(ThemeAssignment.weight.desc(), DocumentChunk.id)
            .limit(disc.N_EXCERPTS * 10)
        ).all()
        want = [r[0].id for r in svc._distinct_documents(rows)[: disc.N_EXCERPTS]]  # noqa: SLF001
        assert [e.chunk_id for e in v.excerpts] == want


def svc_ws_id(db):

    return db.scalars(select_ws("t1")).one().id


def select_ws(slug):
    from sqlalchemy import select

    from app.db.models import Workspace

    return select(Workspace).where(Workspace.slug == slug)
