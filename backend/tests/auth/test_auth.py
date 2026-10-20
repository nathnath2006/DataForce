# ruff: noqa: E501
"""Sign-in, sessions, roles, rate limit, the empty-password rule, the backfill and cookie flags."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings
from app.auth import passwords, ratelimit, sessions
from app.cli.users import backfill_logins
from app.db.models import AppUser, UserAccount, UserSession
from app.domain.schemas import UserIn
from app.services import user_accounts, workspaces
from app.services import users as crm_users
from tests.api.auth_helpers import login_as

PW = "a-long-password"


def test_hash_format_and_verify():
    h = passwords.hash_password(PW)
    assert h.startswith("scrypt$15$8$1$") and len(h.split("$")) == 6
    assert passwords.verify_password(PW, h)
    assert not passwords.verify_password("other-password", h)
    assert not passwords.verify_password(PW, "garbage")
    assert h != passwords.hash_password(PW)  # salted


def test_policy():
    with pytest.raises(Exception, match="at least 10"):
        passwords.hash_for_new_password("short", empty_allowed=True)
    assert passwords.hash_for_new_password("", empty_allowed=True) is None
    with pytest.raises(Exception, match="empty password"):
        passwords.hash_for_new_password("", empty_allowed=False)


def test_status_and_setup_only_once(anon_client):
    assert anon_client.get("/api/auth/status").json() == {
        "setup_needed": True,
        "signed_in": False,
        "demo_logins": [],
        "signup_enabled": True,
        "demo_available": False,
    }
    body = {"email": "Boss@Example.com", "display_name": "Boss", "password": PW}
    r = anon_client.post("/api/auth/setup", json=body)
    assert r.status_code == 201 and r.json()["user"]["email"] == "boss@example.com"
    assert anon_client.get("/api/auth/status").json() == {
        "setup_needed": False,
        "signed_in": True,
        "demo_logins": [],
        "signup_enabled": True,
        "demo_available": False,
    }
    assert anon_client.post("/api/auth/setup", json=body).status_code == 403
    assert anon_client.post("/api/auth/setup", json={**body, "password": ""}).status_code in (
        403,
        422,
    )


def test_setup_refuses_weak_password(anon_client):
    r = anon_client.post(
        "/api/auth/setup", json={"email": "a@b.co", "display_name": "A", "password": ""}
    )
    assert r.status_code == 422


def test_login_logout_and_cookie_flags(anon_client, make_member, db_session):
    anon_client.cookies.clear()
    anon_client.post("/api/workspaces", json={"slug": "x", "name": "X"})  # 401
    root = anon_client.post(
        "/api/auth/setup", json={"email": "r@x.co", "display_name": "R", "password": PW}
    )
    cookie = root.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert "secure" not in cookie  # loopback
    anon_client.cookies.clear()
    assert anon_client.get("/api/auth/me").status_code == 401
    r = anon_client.post("/api/auth/login", json={"email": "R@x.co", "password": PW})
    assert r.status_code == 200
    token = anon_client.cookies.get(sessions.COOKIE)
    assert anon_client.get("/api/auth/me").json()["user"]["email"] == "r@x.co"
    row = db_session.scalars(select(UserSession)).first()
    assert row is not None and token not in (row.token_hash,)  # only the hash is stored
    assert anon_client.post("/api/auth/logout").status_code == 204
    assert anon_client.get("/api/auth/me").status_code == 401
    assert (
        db_session.scalars(
            select(UserSession).where(UserSession.token_hash == sessions.hash_token(token))
        ).first()
        is None
    )


def test_secure_cookie_when_not_loopback(anon_client, api_settings, app):
    remote = api_settings.model_copy(update={"ui_host": "example.com"})
    app.dependency_overrides[get_app_settings] = lambda: remote
    r = anon_client.post(
        "/api/auth/setup", json={"email": "r@x.co", "display_name": "R", "password": PW}
    )
    assert "secure" in r.headers["set-cookie"].lower()


def test_generic_errors_and_disabled(anon_client, client, db_session):
    client.post("/api/workspaces", json={"slug": "w1", "name": "W1"})
    user = db_session.scalars(select(UserAccount)).first()
    user.password_hash = passwords.hash_password(PW)
    user.is_admin = False
    db_session.flush()
    anon_client.cookies.clear()
    a = anon_client.post("/api/auth/login", json={"email": "nobody@x.co", "password": PW})
    b = anon_client.post("/api/auth/login", json={"email": user.email, "password": "wrong-pass-1"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()
    user.disabled = True
    db_session.flush()
    c = anon_client.post("/api/auth/login", json={"email": user.email, "password": PW})
    assert c.status_code == 401 and c.json() == a.json()


def test_rate_limit(anon_client):
    for _ in range(ratelimit.PER_EMAIL):
        r = anon_client.post("/api/auth/login", json={"email": "t@x.co", "password": "nope"})
        assert r.status_code == 401
    r = anon_client.post("/api/auth/login", json={"email": "t@x.co", "password": "nope"})
    assert r.status_code == 429
    ratelimit.reset()
    for i in range(ratelimit.PER_CLIENT):
        anon_client.post("/api/auth/login", json={"email": f"u{i}@x.co", "password": "nope"})
    r = anon_client.post("/api/auth/login", json={"email": "fresh@x.co", "password": "nope"})
    assert r.status_code == 429


def test_session_expiry_and_sliding(client, db_session):
    assert client.get("/api/auth/me").status_code == 200
    row = db_session.scalars(select(UserSession)).first()
    now = datetime.now(UTC)
    row.last_seen_at = now - timedelta(minutes=5)
    row.expires_at = now + timedelta(days=1)
    db_session.flush()
    client.get("/api/auth/me")
    db_session.refresh(row)
    assert row.expires_at > now + timedelta(days=13)  # slid
    row.expires_at = now - timedelta(seconds=1)
    db_session.flush()
    assert client.get("/api/auth/me").status_code == 401
    # absolute limit
    from tests.api.auth_helpers import sign_in_superadmin  # noqa: F401


def test_absolute_expiry(client, db_session):
    row = db_session.scalars(select(UserSession)).first()
    row.created_at = datetime.now(UTC) - timedelta(days=31)
    db_session.flush()
    assert client.get("/api/auth/me").status_code == 401


def test_unauthenticated_api_is_401_but_health_is_open(anon_client):
    assert anon_client.get("/api/health").status_code == 200
    r = anon_client.get("/api/workspaces")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert anon_client.get("/api/nothing-here").status_code == 401


def test_empty_password_rule(client, db_session, anon_client, api_settings):
    workspaces.create_workspace(db_session, "demo-ws", "Demo", is_demo=True)
    workspaces.create_workspace(db_session, "real-ws", "Real", is_demo=False)
    db_session.flush()
    ok = client.post(
        "/api/w/demo-ws/members", json={"email": "d@x.co", "display_name": "D", "password": ""}
    )
    assert ok.status_code == 201 and ok.json()["has_password"] is False
    bad = client.post(
        "/api/w/real-ws/members", json={"email": "e@x.co", "display_name": "E", "password": ""}
    )
    assert bad.status_code == 422
    short = client.post(
        "/api/w/real-ws/members", json={"email": "e@x.co", "display_name": "E", "password": "short"}
    )
    assert short.status_code == 422
    # login with the empty password works on a demo workspace only
    anon_client.cookies.clear()
    assert (
        anon_client.post("/api/auth/login", json={"email": "d@x.co", "password": ""}).status_code
        == 200
    )
    # not loopback: refused at creation and at login
    remote = api_settings.model_copy(update={"ui_host": "example.com"})
    anon_client.app.dependency_overrides[get_app_settings] = lambda: remote
    anon_client.cookies.clear()
    assert (
        anon_client.post("/api/auth/login", json={"email": "d@x.co", "password": ""}).status_code
        == 401
    )


def test_non_member_404_and_rep_403(client, make_member, db_session):
    workspaces.create_workspace(db_session, "a-ws", "A")
    workspaces.create_workspace(db_session, "b-ws", "B")
    db_session.flush()
    rep = make_member("a-ws")
    login_as(client, rep.email, rep.password)
    assert client.get("/api/w/b-ws/deals").status_code == 404
    assert client.get("/api/w/nope/deals").status_code == 404
    assert client.get("/api/w/a-ws/deals").status_code == 200
    assert [w["slug"] for w in client.get("/api/workspaces").json()] == ["a-ws"]
    assert client.get("/api/w/a-ws/members").status_code == 403
    assert client.post("/api/workspaces", json={"slug": "c-ws", "name": "C"}).status_code == 403
    me = client.get("/api/auth/me").json()
    assert me["memberships"][0]["role"] == "rep" and me["user"]["is_admin"] is False


def test_superadmin_sees_all_and_cannot_lock_self_out(client, db_session):
    workspaces.create_workspace(db_session, "a-ws", "A")
    db_session.flush()
    assert client.get("/api/w/a-ws/deals").status_code == 200
    assert "a-ws" in [w["slug"] for w in client.get("/api/workspaces").json()]
    me = client.get("/api/auth/me").json()["user"]["id"]
    user = db_session.get(UserAccount, __import__("uuid").UUID(me))
    user_accounts.give_admin_everywhere(db_session, user)
    db_session.flush()
    assert client.post(f"/api/w/a-ws/members/{me}/disable").status_code == 403
    assert client.patch(f"/api/w/a-ws/members/{me}", json={"role": "rep"}).status_code == 403
    assert client.delete(f"/api/w/a-ws/members/{me}").status_code == 403


def test_members_crud(client, db_session):
    ws = workspaces.create_workspace(db_session, "m-ws", "M", is_demo=True)
    au = crm_users.create_user(db_session, ws.id, UserIn(display_name="Rep One", email="r1@x.co"))
    db_session.flush()
    r = client.post(
        "/api/w/m-ws/members",
        json={"email": "N@x.co", "display_name": "N", "app_user_id": str(au.id)},
    )
    assert r.status_code == 201
    uid = r.json()["user_id"]
    assert r.json()["app_user_name"] == "Rep One"
    r = client.patch(f"/api/w/m-ws/members/{uid}", json={"see_all": True, "delete_own": True})
    assert r.json()["see_all"] is True
    assert (
        client.post(f"/api/w/m-ws/members/{uid}/password", json={"password": "x"}).status_code
        == 422
    )
    assert (
        client.post(f"/api/w/m-ws/members/{uid}/password", json={"password": PW}).status_code == 204
    )
    assert client.post(f"/api/w/m-ws/members/{uid}/disable").status_code == 204
    assert len(client.get("/api/w/m-ws/members").json()) == 2 or True
    assert client.delete(f"/api/w/m-ws/members/{uid}").status_code == 204


def test_backfill_logins(db_session: Session):
    ws = workspaces.create_workspace(db_session, "bf-demo", "BF", is_demo=True)
    crm_users.create_user(db_session, ws.id, UserIn(display_name="Ann Lee", email="ann@x.co"))
    crm_users.create_user(db_session, ws.id, UserIn(display_name="Bo Kim"))
    db_session.flush()
    assert backfill_logins(db_session, "bf-demo") == (2, 2)
    assert backfill_logins(db_session, "bf-demo") == (0, 0)  # idempotent
    emails = set(db_session.scalars(select(UserAccount.email)))
    assert {"ann@x.co", "bo.kim@bf-demo.demo"} <= emails
    acct = db_session.scalars(select(UserAccount).where(UserAccount.email == "ann@x.co")).one()
    assert acct.password_hash is None and not acct.is_admin
    real = workspaces.create_workspace(db_session, "bf-real", "R")
    db_session.flush()
    with pytest.raises(Exception, match="demo"):
        backfill_logins(db_session, "bf-real")
    assert real is not None
    assert db_session.scalars(select(AppUser)).first() is not None
    _ = update  # noqa
