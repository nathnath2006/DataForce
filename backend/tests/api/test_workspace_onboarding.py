"""Test workspaces filled in the background: create, status, delete."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.routes import workspaces as routes
from app.db.models import Account, Deal, Membership, UserAccount, Workspace
from app.services import workspace_setup
from tests.api.conftest import login_as

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _clean_registry():
    workspace_setup.join(120)
    workspace_setup._jobs.clear()
    yield
    workspace_setup.join(120)
    workspace_setup._jobs.clear()


def _create_test(client: TestClient, slug: str = "try-me"):
    return client.post("/api/workspaces", json={"slug": slug, "name": "Try me", "kind": "test"})


def test_test_workspace_fills_in_the_background(client: TestClient, db_session):
    r = _create_test(client)
    assert r.status_code == 201
    body = r.json()
    assert body["is_demo"] is True and body["setup_state"] == "preparing"
    workspace_setup.join(120)
    setup = client.get("/api/workspaces/try-me/setup").json()
    assert setup == {"state": "ready", "step": None, "done": 8, "total": 8, "error": None}
    listed = next(w for w in client.get("/api/workspaces").json() if w["slug"] == "try-me")
    assert listed["setup_state"] == "ready" and listed["n_deals"] > 0 and listed["n_accounts"] > 0
    ws = db_session.scalars(select(Workspace).where(Workspace.slug == "try-me")).one()
    db_session.refresh(ws)
    assert ws.setup_state is None
    n_logins = db_session.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.workspace_id == ws.id, Membership.role == "rep")
    )
    assert n_logins >= 6
    assert db_session.scalar(select(func.count()).select_from(Deal)) > 0
    assert db_session.scalar(select(func.count()).select_from(Account)) > 0


def test_real_create_is_unchanged(client: TestClient):
    r = client.post("/api/workspaces", json={"slug": "real-one", "name": "Real"})
    assert r.status_code == 201
    assert r.json()["is_demo"] is False and r.json()["setup_state"] == "ready"
    assert client.get("/api/workspaces/real-one/setup").json()["state"] == "ready"


def test_status_reports_the_current_step(client: TestClient, db_session):
    db_session.add(Workspace(slug="busy", name="Busy", is_demo=True, setup_state="preparing"))
    db_session.commit()
    assert workspace_setup.reserve("busy")
    workspace_setup._set_step("busy", "deals")
    body = client.get("/api/workspaces/busy/setup").json()
    assert body == {"state": "preparing", "step": "deals", "done": 4, "total": 8, "error": None}


def test_one_fill_at_a_time(client: TestClient):
    assert workspace_setup.reserve("someone-else")
    r = _create_test(client)
    assert r.status_code == 409 and "already being prepared" in r.text
    assert client.get("/api/workspaces/try-me/setup").status_code == 404  # nothing was created


def test_quota_refuses_a_test_workspace(client: TestClient, monkeypatch):
    monkeypatch.setattr(routes, "db_size", lambda db, quota: {"used_pct": 93.0})
    r = _create_test(client)
    assert r.status_code == 409 and "93% full" in r.text
    assert not workspace_setup.is_running()


def test_failed_fill_deletes_the_workspace_and_reports_it(client: TestClient, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("secret postgres://user:pw@host/db")

    monkeypatch.setattr(workspace_setup, "generate", boom)
    assert _create_test(client).status_code == 201
    workspace_setup.join(120)
    r = client.get("/api/workspaces/try-me/setup")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "failed" and body["error"] == workspace_setup.FAILED_MESSAGE
    assert "postgres" not in r.text
    assert "try-me" not in [w["slug"] for w in client.get("/api/workspaces").json()]
    assert not workspace_setup.is_running()


def test_interrupted_when_no_job_runs(client: TestClient, db_session):
    ws = Workspace(slug="half", name="Half", is_demo=True, setup_state="preparing")
    db_session.add(ws)
    db_session.commit()
    body = client.get("/api/workspaces/half/setup").json()
    assert body["state"] == "interrupted" and body["error"] is None
    listed = next(w for w in client.get("/api/workspaces").json() if w["slug"] == "half")
    assert listed["setup_state"] == "preparing"
    assert client.delete("/api/workspaces/half").status_code == 204
    assert client.get("/api/workspaces/half/setup").status_code == 404


def test_delete_rules(client: TestClient, db_session):
    client.post("/api/workspaces", json={"slug": "keep-me", "name": "Real"})
    assert client.delete("/api/workspaces/keep-me").status_code == 403
    assert client.delete("/api/workspaces/missing").status_code == 404
    db_session.add(Workspace(slug="demo-x", name="D", is_demo=True, setup_state="preparing"))
    db_session.commit()
    assert workspace_setup.reserve("demo-x")
    assert client.delete("/api/workspaces/demo-x").status_code == 409
    workspace_setup.release("demo-x")
    assert client.delete("/api/workspaces/demo-x").status_code == 204


def test_non_admin_is_refused(client: TestClient, make_member, db_session):
    client.post("/api/workspaces", json={"slug": "team", "name": "Team"})
    db_session.add(Workspace(slug="demo-y", name="D", is_demo=True))
    db_session.commit()
    m = make_member("team")
    login_as(client, m.email, m.password)
    assert _create_test(client).status_code == 403
    assert client.get("/api/workspaces/team/setup").status_code == 403
    assert client.get("/api/workspaces/nope/setup").status_code == 403  # no existence leak
    assert client.delete("/api/workspaces/demo-y").status_code == 403
    assert db_session.scalar(select(func.count()).select_from(UserAccount)) > 0
