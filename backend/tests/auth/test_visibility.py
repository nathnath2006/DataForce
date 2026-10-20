"""Row visibility, server-set authors, deletes and admin-only routes (M5, L2).

Two reps A and B share one workspace. A owns `accA` (deal dA), B owns `accB` (deal dB), `accU`
and its deal are unowned, and `accS` is shared: A and B each own one deal on it. The viewer
dependency is overridden, so these tests do not depend on the login code.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.api.deps import get_viewer
from app.api.routes.flows import get_loader_session_factory
from app.assistant.context import build_context
from app.auth.viewer import Viewer
from app.config import Settings
from app.db.models import Account, AppUser, Deal, Workspace
from app.flows.sources.crm import load_crm_table
from app.services import flows as flow_service
from app.services import genai
from app.services.errors import NotFoundError

pytestmark = pytest.mark.integration
NOW = datetime.now(UTC)
CRM = {"kind": "crm", "table": "deals"}


@pytest.fixture
def world(client, app, session_factory):
    flow_service._slots = None
    app.dependency_overrides[get_loader_session_factory] = lambda: session_factory
    client.post("/api/workspaces", json={"slug": "vis", "name": "Vis"})
    base = "/api/w/vis"
    a = client.post(f"{base}/users", json={"display_name": "Rep A"}).json()["id"]
    b = client.post(f"{base}/users", json={"display_name": "Rep B"}).json()["id"]
    with session_factory() as s:
        ws = s.scalars(select(Workspace).where(Workspace.slug == "vis")).one()
        ws_id = ws.id
    day = (NOW - timedelta(days=30)).date().isoformat()
    ids: dict[str, str] = {}

    def account(key, owner=None):
        body = {"name": key}
        if owner:
            body["owner_id"] = owner
        ids[key] = client.post(f"{base}/accounts", json=body).json()["id"]

    def deal(key, acc, owner=None, amount="1000"):
        body = {"account_id": ids[acc], "name": key, "created_on": day, "amount_eur": amount}
        if owner:
            body["owner_id"] = owner
        ids[key] = client.post(f"{base}/deals", json=body).json()["id"]

    account("accA", a)
    account("accB", b)
    account("accU")
    account("accS")
    deal("dA", "accA", a)
    deal("dB", "accB", b, "5000")
    deal("dU", "accU", None, "300")
    deal("dSA", "accS", a, "200")
    deal("dSB", "accS", b, "7000")
    for acc in ("accA", "accB", "accU", "accS"):
        ids["c" + acc] = client.post(
            f"{base}/contacts", json={"account_id": ids[acc], "full_name": f"Person {acc}"}
        ).json()["id"]
        client.post(f"{base}/contacts/{ids['c' + acc]}/notes", json={"body": f"note {acc}"})
        client.post(f"{base}/accounts/{ids[acc]}/comments", json={"body": f"comment {acc}"})
        client.post(
            f"{base}/accounts/{ids[acc]}/activities",
            json={
                "kind": "call",
                "occurred_at": (NOW - timedelta(days=1)).isoformat(),
                "subject": f"call {acc}",
            },
        )
        client.post(f"{base}/tasks", json={"title": f"task {acc}", "account_id": ids[acc]})

    def viewer(user, **kw):
        return Viewer(
            workspace_id=ws_id, user_id=uuid.uuid4(), app_user_id=uuid.UUID(user), role="rep", **kw
        )

    class W:
        pass

    w = W()
    w.base, w.ids, w.a, w.b, w.ws_id = base, ids, a, b, ws_id
    w.viewer = viewer
    w.app = app

    def act_as(v):
        app.dependency_overrides[get_viewer] = lambda: v

    w.act_as = act_as
    w.admin = lambda: app.dependency_overrides.pop(get_viewer, None)
    yield w
    app.dependency_overrides.pop(get_viewer, None)
    flow_service._slots = None


def names(resp):
    body = resp.json()
    return {x["name"] for x in (body["items"] if isinstance(body, dict) else body)}


def test_rep_sees_only_own_rows(client, world):
    w = world
    w.act_as(w.viewer(w.a))
    assert names(client.get(f"{w.base}/deals")) == {"dA", "dSA"}
    assert names(client.get(f"{w.base}/accounts")) == {"accA", "accS"}
    contacts = {c["full_name"] for c in client.get(f"{w.base}/contacts").json()["items"]}
    assert contacts == {"Person accA", "Person accS"}
    # the shared account shows only A's deal in its counts
    acc = client.get(f"{w.base}/accounts/{w.ids['accS']}").json()
    assert acc["n_deals"] == 1
    tasks = {t["title"] for t in client.get(f"{w.base}/tasks").json()["items"]}
    assert tasks == {"task accA", "task accS"}
    assert client.get(f"{w.base}/accounts/{w.ids['accA']}/activities").status_code == 200
    comps = client.get(f"{w.base}/documents").json()
    assert comps["total"] == 0
    tl = client.get(f"{w.base}/accounts/{w.ids['accS']}/timeline").json()["items"]
    assert not any("accB" in i["title"] or "accU" in i["title"] for i in tl)
    assert any("accS" in i["title"] for i in tl)


def test_other_reps_ids_are_404(client, world):
    w = world
    w.act_as(w.viewer(w.a))
    i = w.ids
    for path in (
        f"deals/{i['dB']}",
        f"deals/{i['dSB']}",
        f"accounts/{i['accB']}",
        f"accounts/{i['accU']}",
        f"contacts/{i['caccB']}",
        f"contacts/{i['caccB']}/notes",
        f"accounts/{i['accB']}/comments",
        f"accounts/{i['accB']}/activities",
        f"accounts/{i['accB']}/timeline",
        f"deals/{i['dB']}/timeline",
        f"deals/{i['dB']}/activities",
        f"accounts/{i['accB']}/org-chart",
        f"accounts/{i['accB']}/tasks",
    ):
        assert client.get(f"{w.base}/{path}").status_code == 404, path
    assert (
        client.post(f"{w.base}/contacts/{i['caccB']}/notes", json={"body": "x"}).status_code == 404
    )
    assert client.patch(f"{w.base}/deals/{i['dB']}", json={"name": "hack"}).status_code == 404
    assert (
        client.post(f"{w.base}/deals/{i['dB']}/move", json={"stage": "qualification"}).status_code
        == 404
    )


def test_see_all_lifts_the_filter(client, world):
    w = world
    w.act_as(w.viewer(w.a, see_all=True))
    assert len(names(client.get(f"{w.base}/deals"))) == 5
    assert len(names(client.get(f"{w.base}/accounts"))) == 4
    assert client.get(f"{w.base}/deals/{w.ids['dB']}").status_code == 200


def test_unowned_visible_to_admin_only(client, world):
    w = world
    assert "accU" in names(client.get(f"{w.base}/accounts"))  # the (default) admin
    w.act_as(w.viewer(w.b))
    assert "accU" not in names(client.get(f"{w.base}/accounts"))


def test_analytics_computed_on_own_rows(client, world, db_session, session_factory):
    w = world
    w.act_as(w.viewer(w.a))
    pipe = client.get(f"{w.base}/stats/pipeline").json()
    assert pipe["n_deals"] == 2 and pipe["total_amount_eur"] == 1200
    q = client.get(f"{w.base}/quality").json()
    amounts = next(c for c in q["checks"] if c["id"] == "amounts")
    assert amounts["total"] == 2
    res = client.post(
        f"{w.base}/viz/query",
        json={"source": CRM, "measures": [{"column": "amount_eur", "agg": "sum"}]},
    ).json()
    assert res["n_source_rows"] == 2 and res["rows"] == [[1200.0]]
    # flow CRM loader
    v = w.viewer(w.a)
    df = load_crm_table(db_session, w.ws_id, "deals", 1000, v)
    assert set(df["deal_name"]) == {"dA", "dSA"}
    assert set(load_crm_table(db_session, w.ws_id, "accounts", 1000, v)["account_name"]) == {
        "accA",
        "accS",
    }
    assert len(load_crm_table(db_session, w.ws_id, "tasks", 1000, v)) == 2
    assert len(load_crm_table(db_session, w.ws_id, "deals", 1000, None)) == 5
    # a rep cannot run a flow over an uploaded file
    run = client.post(
        f"{w.base}/flows/run",
        json={
            "graph": {
                "version": 1,
                "nodes": [
                    {
                        "id": "d",
                        "position": {"x": 0, "y": 0},
                        "config": {
                            "type": "dataset",
                            "dataset": {"source": "file", "file_id": str(uuid.uuid4())},
                        },
                    }
                ],
                "edges": [],
            }
        },
    )
    assert run.status_code == 200
    node = run.json()["results"]["d"]
    assert node["status"] == "error" and "administrator" in node["error"]
    # assistant context and GenAI source
    ctx, _ = build_context(
        db_session, w.ws_id, "account", uuid.UUID(w.ids["accS"]), max_chars=50_000, viewer=v
    )
    text = ctx.render()
    assert "Number of deals: 1" in text and "dSB" not in text and "7000" not in text
    with pytest.raises(NotFoundError):
        build_context(
            db_session, w.ws_id, "account", uuid.UUID(w.ids["accB"]), max_chars=50_000, viewer=v
        )
    settings = Settings(_env_file=None)
    src = genai.collect(
        db_session, w.ws_id, settings, account_id=uuid.UUID(w.ids["accS"]), viewer=v
    )
    blob = " ".join(i.text for i in src.items)
    assert "dSA" in blob and "dSB" not in blob
    with pytest.raises(NotFoundError):
        genai.collect(db_session, w.ws_id, settings, deal_id=uuid.UUID(w.ids["dB"]), viewer=v)
    # the assistant route
    r = client.get(f"{w.base}/assistant/scope", params={"kind": "account", "id": w.ids["accB"]})
    assert r.status_code == 404


def test_theme_and_scan_runs_are_per_viewer(client, world):
    w = world
    w.act_as(w.viewer(w.a))
    assert client.post(f"{w.base}/stats/scan").status_code == 200
    w.act_as(w.viewer(w.b))
    assert client.get(f"{w.base}/stats/scan/latest").status_code == 404  # A's scan is not B's
    w.admin()
    assert client.get(f"{w.base}/stats/scan/latest").status_code == 404


def test_deletes_need_the_right_and_ownership(client, world):
    w = world
    i = w.ids
    w.act_as(w.viewer(w.a))
    assert client.delete(f"{w.base}/deals/{i['dA']}").status_code == 403
    w.act_as(w.viewer(w.a, delete_own=True))
    assert client.delete(f"{w.base}/deals/{i['dB']}").status_code == 404  # not visible
    assert client.delete(f"{w.base}/deals/{i['dSB']}").status_code == 404
    assert client.delete(f"{w.base}/deals/{i['dA']}").status_code == 204
    # a see-all rep with delete-own sees the other's deal but may not delete it
    w.act_as(w.viewer(w.a, see_all=True, delete_own=True))
    assert client.delete(f"{w.base}/deals/{i['dB']}").status_code == 403
    # a note: only its author
    note = client.post(f"{w.base}/contacts/{i['caccA']}/notes", json={"body": "mine"}).json()
    assert client.delete(f"{w.base}/notes/{note['id']}").status_code == 200
    w.act_as(w.viewer(w.b, see_all=True, delete_own=True))
    other = client.get(f"{w.base}/contacts/{i['caccA']}/notes").json()[0]
    assert client.delete(f"{w.base}/notes/{other['id']}").status_code == 403
    # erasure is admin only, even with delete-own
    assert client.delete(f"{w.base}/contacts/{i['caccA']}").status_code == 403
    assert client.delete(f"{w.base}/accounts/{i['accA']}").status_code == 403
    w.admin()
    assert client.delete(f"{w.base}/deals/{i['dB']}").status_code == 204


def test_authors_and_owners_are_set_by_the_server(client, world):
    w = world
    i = w.ids
    w.act_as(w.viewer(w.a))
    note = client.post(f"{w.base}/contacts/{i['caccA']}/notes", json={"body": "hi"}).json()
    assert note["author_id"] == w.a
    spoof = client.post(
        f"{w.base}/contacts/{i['caccA']}/notes", json={"body": "hi", "author_id": w.b}
    )
    assert spoof.status_code == 422
    act = client.post(
        f"{w.base}/accounts/{i['accA']}/activities",
        json={
            "kind": "call",
            "occurred_at": (NOW - timedelta(hours=1)).isoformat(),
            "subject": "s",
            "author_id": w.b,
        },
    )
    assert act.status_code == 422
    act = client.post(
        f"{w.base}/accounts/{i['accA']}/activities",
        json={
            "kind": "call",
            "occurred_at": (NOW - timedelta(hours=1)).isoformat(),
            "subject": "s",
        },
    ).json()
    assert act["author_id"] == w.a
    task = client.post(f"{w.base}/tasks", json={"title": "t", "account_id": i["accA"]}).json()
    assert task["owner_id"] == w.a
    assert (
        client.post(
            f"{w.base}/tasks", json={"title": "t", "account_id": i["accA"], "owner_id": w.b}
        ).status_code
        == 422
    )
    moved = client.post(f"{w.base}/deals/{i['dA']}/move", json={"stage": "qualification"})
    assert moved.status_code == 200
    ev = client.get(f"{w.base}/deals/{i['dA']}/stage-events").json()
    assert ev[-1]["changed_by_id"] == w.a
    assert (
        client.post(
            f"{w.base}/deals/{i['dA']}/move", json={"stage": "proposal", "changed_by_id": w.b}
        ).status_code
        == 422
    )
    # owners: default to the viewer, only an admin names another
    mine = client.post(
        f"{w.base}/deals",
        json={"account_id": i["accA"], "name": "new", "created_on": date.today().isoformat()},
    ).json()
    assert mine["owner_id"] == w.a
    assert (
        client.post(
            f"{w.base}/deals",
            json={
                "account_id": i["accA"],
                "name": "x",
                "owner_id": w.b,
                "created_on": date.today().isoformat(),
            },
        ).status_code
        == 403
    )
    assert client.patch(f"{w.base}/deals/{i['dA']}", json={"owner_id": w.b}).status_code == 403
    new_acc = client.post(f"{w.base}/accounts", json={"name": "mine"}).json()
    assert new_acc["owner_id"] == w.a
    w.admin()
    ok = client.patch(f"{w.base}/deals/{i['dA']}", json={"owner_id": w.b})
    assert ok.status_code == 200 and ok.json()["owner_id"] == w.b


ADMIN_ONLY = [
    ("get", "/ai", None),
    ("put", "/ai", {"provider": "anthropic", "model": "m", "api_key": "k" * 20}),
    ("delete", "/ai", None),
    ("get", "/connectors/tamtam", None),
    ("post", "/connectors/tamtam/connect", None),
    ("get", "/mailbox", None),
    ("post", "/mailbox/sync", None),
    ("post", "/mailbox/gmail/connect", None),
    ("get", "/files", None),
    ("get", "/connections", None),
    ("get", "/admin/overview", None),
    ("get", "/admin/runs", None),
    ("get", "/agent", None),
    ("post", "/users", {"display_name": "X"}),
]


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ONLY)
def test_admin_only_routes_refuse_a_rep(client, world, method, path, body):
    w = world
    w.act_as(w.viewer(w.a, see_all=True, delete_own=True))
    r = getattr(client, method)(f"{w.base}{path}", **({"json": body} if body else {}))
    assert r.status_code == 403, (path, r.status_code, r.text)
    assert "administrator" in r.text
    w.admin()
    assert (
        getattr(client, method)(f"{w.base}{path}", **({"json": body} if body else {})).status_code
        != 403
    )


def test_viewer_without_identity_sees_nothing_owned(client, world):
    w = world
    w.act_as(Viewer(workspace_id=w.ws_id, user_id=uuid.uuid4(), app_user_id=None, role="rep"))
    assert client.get(f"{w.base}/deals").json()["total"] == 0
    assert client.get(f"{w.base}/accounts").json()["total"] == 0


def test_account_owner_column_backs_visibility(client, world, db_session):
    w = world
    acc = db_session.get(Account, uuid.UUID(w.ids["accA"]))
    assert acc.owner_id == uuid.UUID(w.a)
    assert db_session.get(AppUser, uuid.UUID(w.b)) is not None
    assert db_session.scalar(select(Deal.owner_id).where(Deal.id == uuid.UUID(w.ids["dU"]))) is None


def test_home_counts_only_own_rows(client, world):
    w = world
    w.act_as(w.viewer(w.a))
    h = client.get(f"{w.base}/home").json()
    assert h["kpis"]["open_deals"] == 2
    assert float(h["kpis"]["open_pipeline_eur"]) == 1200
    assert {d["name"] for d in h["open_deals"]} == {"dA", "dSA"}
    assert all(a["deal_name"] in ("dA", "dSA") for a in h["activity"])
    # the admin sees everyone, and can look at one rep
    w.admin()
    assert client.get(f"{w.base}/home").json()["kpis"]["open_deals"] == 5
    mine = client.get(f"{w.base}/home", params={"owner": w.a}).json()
    assert mine["kpis"]["open_deals"] == 2
    assert float(mine["kpis"]["open_pipeline_eur"]) == 1200
    theirs = client.get(f"{w.base}/home", params={"owner": w.b}).json()
    assert float(theirs["kpis"]["open_pipeline_eur"]) == 12000


def test_home_owner_is_for_admin_and_see_all_only(client, world):
    w = world
    w.act_as(w.viewer(w.a))
    assert client.get(f"{w.base}/home", params={"owner": w.b}).status_code == 403
    assert client.get(f"{w.base}/home", params={"owner": w.a}).status_code == 200
    assert client.get(f"{w.base}/quality", params={"owner": w.b}).status_code == 403
    w.act_as(w.viewer(w.a, see_all=True))
    h = client.get(f"{w.base}/home", params={"owner": w.b}).json()
    assert float(h["kpis"]["open_pipeline_eur"]) == 12000
    assert client.get(f"{w.base}/home", params={"owner": str(uuid.uuid4())}).status_code == 404


def test_quality_per_rep(client, world):
    w = world

    def amounts(**params):
        q = client.get(f"{w.base}/quality", params=params).json()
        return next(c for c in q["checks"] if c["id"] == "amounts")["total"]

    assert amounts() == 5  # the admin: everyone
    assert amounts(owner=w.a) == 2
    assert amounts(owner=w.b) == 2
    w.act_as(w.viewer(w.a))
    assert amounts() == 2


def test_tasks_page_filters_and_visibility(client, world):
    w = world
    w.act_as(w.viewer(w.a))
    page = client.get(f"{w.base}/tasks", params={"limit": 1}).json()
    assert page["total"] == 2 and len(page["items"]) == 1 and page["limit"] == 1
    assert page["items"][0]["account_name"] in ("accA", "accS")
    assert client.get(f"{w.base}/tasks", params={"due": "none"}).json()["total"] == 2
    assert client.get(f"{w.base}/tasks", params={"due": "overdue"}).json()["total"] == 0
    assert client.get(f"{w.base}/tasks", params={"status": "done"}).json()["total"] == 0
    assert client.get(f"{w.base}/tasks", params={"due": "nope"}).status_code == 422
    assert client.get(f"{w.base}/tasks", params={"deal_id": w.ids["dB"]}).status_code == 404


def test_activities_page(client, world):
    w = world
    w.act_as(w.viewer(w.a))
    page = client.get(f"{w.base}/activities").json()
    assert {i["subject"] for i in page["items"]} == {"call accA", "call accS"}
    assert page["total"] == 2 and page["items"][0]["account_name"]
    assert client.get(f"{w.base}/activities", params={"kind": "email"}).json()["total"] == 0
    assert (
        client.get(f"{w.base}/activities", params={"date_from": "2999-01-01"}).json()["total"] == 0
    )
    today = datetime.now(UTC).date().isoformat()
    both = client.get(f"{w.base}/activities", params={"date_to": today}).json()
    assert both["total"] == 2
