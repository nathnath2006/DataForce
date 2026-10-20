"""SR20: the M5 login and visibility review fixes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.auth import ratelimit, sessions
from app.db.models import Account, Activity, Deal, SavedModel, Task, UserAccount
from app.domain.schemas import UserIn
from app.services import user_accounts, workspaces
from app.services import users as crm_users
from tests.api.auth_helpers import login_as

pytestmark = pytest.mark.integration
PW = "a-long-password"


def test_workspace_admin_cannot_take_over_a_superadmin_or_foreign_user(
    client, make_member, db_session
):
    a = workspaces.create_workspace(db_session, "a-ws", "A")
    workspaces.create_workspace(db_session, "b-ws", "B")
    db_session.flush()
    root_id = uuid.UUID(client.get("/api/auth/me").json()["user"]["id"])
    root = db_session.get(UserAccount, root_id)
    user_accounts.add_membership(db_session, root, a, role="admin")
    foreign = make_member("b-ws")
    user_accounts.add_membership(db_session, db_session.get(UserAccount, foreign.user_id), a)
    local = make_member("a-ws")
    adm = make_member("a-ws", role="admin")
    db_session.flush()
    root_cookie = client.cookies.get(sessions.COOKIE)

    login_as(client, adm.email, adm.password)
    for victim in (root_id, foreign.user_id):
        base = f"/api/w/a-ws/members/{victim}"
        assert client.post(f"{base}/password", json={"password": PW}).status_code == 403
        assert client.post(f"{base}/disable").status_code == 403
        assert client.post(f"{base}/enable").status_code == 403
        assert client.patch(base, json={"display_name": "Pwned"}).status_code == 403
    assert db_session.get(UserAccount, root_id).password_hash is None
    # a user who is only in this workspace is still manageable
    base = f"/api/w/a-ws/members/{local.user_id}"
    assert client.post(f"{base}/password", json={"password": PW}).status_code == 204

    client.cookies.clear()
    client.cookies.set(sessions.COOKIE, root_cookie)
    base = f"/api/w/a-ws/members/{foreign.user_id}"
    assert client.post(f"{base}/password", json={"password": PW}).status_code == 204
    assert client.post(f"{base}/disable").status_code == 204
    assert client.post(f"{base}/enable").status_code == 204
    assert client.patch(base, json={"display_name": "Renamed"}).status_code == 200


def _shared_account(db_session):
    ws = workspaces.create_workspace(db_session, "sh-ws", "S", is_demo=True)
    a = crm_users.create_user(db_session, ws.id, UserIn(display_name="Rep A"))
    b = crm_users.create_user(db_session, ws.id, UserIn(display_name="Rep B"))
    acc = Account(workspace_id=ws.id, name="Shared")
    db_session.add(acc)
    db_session.flush()
    deals = {}
    for k, u in (("a", a), ("b", b)):
        d = Deal(
            workspace_id=ws.id,
            account_id=acc.id,
            owner_id=u.id,
            name=f"Deal {k}",
            created_on=datetime.now(UTC).date(),
        )
        db_session.add(d)
        deals[k] = d
    db_session.flush()
    now = datetime.now(UTC)
    act = Activity(
        workspace_id=ws.id,
        account_id=acc.id,
        deal_id=deals["b"].id,
        kind="call",
        subject="B secret",
        occurred_at=now,
    )
    task = Task(workspace_id=ws.id, account_id=acc.id, deal_id=deals["b"].id, title="B task")
    open_task = Task(workspace_id=ws.id, account_id=acc.id, title="Account task")
    db_session.add_all([act, task, open_task])
    db_session.flush()
    return ws, a, b, acc, act, task


def test_deal_level_rows_of_another_rep_are_hidden(client, make_member, db_session):
    ws, a, _b, acc, act, task = _shared_account(db_session)
    rep = make_member("sh-ws", app_user_id=a.id)
    login_as(client, rep.email, rep.password)
    base = "/api/w/sh-ws"
    acts = client.get(f"{base}/accounts/{acc.id}/activities").json()
    assert "B secret" not in str(acts)
    tasks = client.get(f"{base}/accounts/{acc.id}/tasks").json()
    assert [t["title"] for t in tasks] == ["Account task"]
    assert [t["title"] for t in client.get(f"{base}/tasks").json()] == ["Account task"]
    tl = client.get(f"{base}/accounts/{acc.id}/timeline").json()
    assert "B secret" not in str(tl) and "B task" not in str(tl)
    assert client.patch(f"{base}/activities/{act.id}", json={"subject": "x"}).status_code == 404
    assert client.patch(f"{base}/tasks/{task.id}", json={"title": "x"}).status_code == 404
    assert client.post(f"{base}/tasks/{task.id}/complete").status_code in (404, 405)
    # the admin still sees all of it
    client.cookies.clear()
    sa = _superadmin(client, db_session)
    assert sa
    assert "B secret" in str(client.get(f"{base}/accounts/{acc.id}/activities").json())


def _superadmin(client, db_session):
    from tests.api.auth_helpers import sign_in_superadmin

    class _F:
        def __call__(self):
            return db_session

    # reuse the test connection through a throwaway factory
    from sqlalchemy.orm import sessionmaker

    sign_in_superadmin(
        client,
        sessionmaker(
            bind=db_session.get_bind(),
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        ),
    )
    return True


def test_setup_runs_under_an_advisory_lock(anon_client, db_session, monkeypatch):
    from sqlalchemy.orm import Session

    seen: list[str] = []
    orig = Session.execute

    def spy(self, stmt, *a, **kw):
        seen.append(str(stmt))
        return orig(self, stmt, *a, **kw)

    monkeypatch.setattr(Session, "execute", spy)
    real = user_accounts.admin_exists

    def exists(db):
        seen.append("ADMIN_EXISTS")
        return real(db)

    monkeypatch.setattr(user_accounts, "admin_exists", exists)
    body = {"email": "boss@x.co", "display_name": "Boss", "password": PW}
    assert anon_client.post("/api/auth/setup", json=body).status_code == 201
    lock = next(i for i, s in enumerate(seen) if "pg_advisory_xact_lock" in s)
    assert lock < seen.index("ADMIN_EXISTS")
    anon_client.cookies.clear()
    assert anon_client.post("/api/auth/setup", json=body).status_code == 403


def test_saved_models_are_scoped_to_their_creator(client, make_member, db_session):
    ws = workspaces.create_workspace(db_session, "mo-ws", "M", is_demo=True)
    a = crm_users.create_user(db_session, ws.id, UserIn(display_name="A"))
    b = crm_users.create_user(db_session, ws.id, UserIn(display_name="B"))
    row = SavedModel(
        workspace_id=ws.id,
        name="B model",
        kind="linear",
        params={},
        features=[],
        metrics={"metrics": []},
        status="exploratory",
        created_by_id=b.id,
    )
    db_session.add(row)
    db_session.flush()
    rep = make_member("mo-ws", app_user_id=a.id)
    login_as(client, rep.email, rep.password)
    base = "/api/w/mo-ws/models"
    assert client.get(base).json() == []
    assert client.get(f"{base}/{row.id}").status_code == 404
    assert client.patch(f"{base}/{row.id}", json={"name": "mine"}).status_code == 404
    owner = make_member("mo-ws", app_user_id=b.id)
    login_as(client, owner.email, owner.password)
    assert [m["name"] for m in client.get(base).json()] == ["B model"]
    assert client.patch(f"{base}/{row.id}", json={"name": "ok"}).status_code == 200
    seeall = make_member("mo-ws", see_all=True)
    login_as(client, seeall.email, seeall.password)
    assert len(client.get(base).json()) == 1


def test_unlink_needs_delete_own(client, make_member, db_session):
    from app.db.models import MailboxConnection, MailboxMessage

    ws, a, _b, acc, _act, _t = _shared_account(db_session)
    deal_a = db_session.scalars(
        select(Deal).where(Deal.owner_id == a.id, Deal.workspace_id == ws.id)
    ).one()
    conn = MailboxConnection(workspace_id=ws.id, provider="gmail")
    db_session.add(conn)
    db_session.flush()
    act = Activity(
        workspace_id=ws.id, account_id=acc.id, deal_id=deal_a.id, kind="email",
        subject="m", occurred_at=datetime.now(UTC), source="mailbox", author_user_id=a.id,
    )  # fmt: skip
    db_session.add(act)
    db_session.flush()
    msg = _message(ws.id, conn.id, deal_a.id, act.id)
    db_session.add(msg)
    db_session.flush()
    rep = make_member("sh-ws", app_user_id=a.id, delete_own=False)
    login_as(client, rep.email, rep.password)
    r = client.post(f"/api/w/sh-ws/mailbox/messages/{msg.id}/unlink")
    assert r.status_code == 403, r.text
    assert db_session.get(Activity, act.id) is not None
    _ = MailboxMessage


def _message(ws_id, conn_id, deal_id, act_id):
    from app.db.models import MailboxMessage

    return MailboxMessage(
        workspace_id=ws_id, connection_id=conn_id, provider_message_id="p1",
        state="linked", suggested_deal_id=deal_id, linked_activity_id=act_id,
        subject="m", from_addr="a@b.co", sent_at=datetime.now(UTC),
    )  # fmt: skip


def test_rate_limiter_is_bounded_and_drops_expired(monkeypatch):
    ratelimit.reset()
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 50)
    for i in range(200):
        ratelimit.record_failure(f"u{i}@x", f"c{i}", now=float(i))
    assert len(ratelimit._fails) <= 50
    later = 200 + ratelimit.WINDOW_S
    ratelimit.check("u199@x", "c199", now=later)
    assert "e:u199@x" not in ratelimit._fails
    for _ in range(ratelimit.PER_EMAIL):
        ratelimit.record_failure("x@x", "cx", now=later)
    with pytest.raises(ratelimit.TooManyAttempts):
        ratelimit.check("x@x", "cx", now=later)
    ratelimit.reset()
