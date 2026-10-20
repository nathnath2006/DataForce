"""Demo logins in /status, forgot / reset password."""

from __future__ import annotations

import logging
import re
import time

from app.api.deps import get_app_settings
from app.auth import passwords, ratelimit, reset
from app.db.models import Membership, UserAccount, Workspace
from app.services import workspaces

PW = "a-long-password"
NEW = "another-long-password"


def _user(db, email, ws_slugs, *, pw=None, admin=False):
    u = UserAccount(
        email=email,
        display_name=email.split("@")[0],
        password_hash=passwords.hash_password(pw) if pw else None,
        is_admin=admin,
    )
    db.add(u)
    db.flush()
    for slug in ws_slugs:
        ws = db.query(Workspace).filter_by(slug=slug).one()
        db.add(Membership(user_account_id=u.id, workspace_id=ws.id, role="rep"))
    db.commit()
    return u


def _link(caplog) -> str:
    m = re.search(r"reset\?token=(\S+)", caplog.text)
    assert m
    return m.group(1)


def test_demo_logins(anon_client, app, api_settings, db_session):
    workspaces.create_workspace(db_session, "d1", "D1", is_demo=True)
    workspaces.create_workspace(db_session, "r1", "R1", is_demo=False)
    _user(db_session, "rep0@demo.example", ["d1"])
    _user(db_session, "mixed@demo.example", ["d1", "r1"])
    _user(db_session, "real@demo.example", ["r1"])
    _user(db_session, "pw@demo.example", ["d1"], pw=PW)
    got = anon_client.get("/api/auth/status").json()["demo_logins"]
    assert got == [{"email": "rep0@demo.example", "display_name": "rep0"}]
    remote = api_settings.model_copy(update={"ui_host": "example.com"})
    app.dependency_overrides[get_app_settings] = lambda: remote
    assert anon_client.get("/api/auth/status").json()["demo_logins"] == []


def test_forgot_same_answer_and_log(anon_client, db_session, caplog):
    _user(db_session, "a@x.co", [], pw=PW)
    caplog.set_level(logging.WARNING)
    r1 = anon_client.post("/api/auth/forgot", json={"email": "A@x.co"})
    assert (
        "Password reset link for a@x.co (valid 15 minutes): http://127.0.0.1:8800/reset?token="
        in (caplog.text)
    )
    caplog.clear()
    r2 = anon_client.post("/api/auth/forgot", json={"email": "nobody@x.co"})
    assert r1.status_code == r2.status_code == 202 and r1.json() == r2.json()
    assert "reset link" not in caplog.text


def test_reset_flow_and_single_use(anon_client, db_session, caplog):
    u = _user(db_session, "a@x.co", [], pw=PW)
    old = anon_client.post("/api/auth/login", json={"email": "a@x.co", "password": PW})
    old_cookie = old.cookies.get("df_session")
    caplog.set_level(logging.WARNING)
    anon_client.post("/api/auth/forgot", json={"email": "a@x.co"})
    token = _link(caplog)
    assert (
        anon_client.post("/api/auth/reset", json={"token": token, "password": "short"}).status_code
        == 422
    )
    r = anon_client.post("/api/auth/reset", json={"token": token, "password": NEW})
    assert r.status_code == 200 and r.json()["user"]["email"] == "a@x.co"
    anon_client.cookies.clear()
    anon_client.cookies.set("df_session", old_cookie)
    assert anon_client.get("/api/auth/me").status_code == 401  # old sessions ended
    again = anon_client.post(
        "/api/auth/reset", json={"token": token, "password": "third-long-password"}
    )
    assert again.status_code == 400 and again.json()["error"]["message"] == (
        "This link is invalid or expired."
    )
    db_session.refresh(u)
    assert passwords.verify_password(NEW, u.password_hash)


def test_reset_rejects_expired_tampered_disabled(anon_client, db_session, api_settings):
    u = _user(db_session, "a@x.co", [], pw=PW)
    bad = "This link is invalid or expired."

    def go(tok):
        r = anon_client.post("/api/auth/reset", json={"token": tok, "password": NEW})
        assert r.status_code == 400 and r.json()["error"]["message"] == bad

    go(reset.make_token(api_settings, u, now=time.time() - 16 * 60))
    good = reset.make_token(api_settings, u)
    go(good[:-3] + ("AAA" if not good.endswith("AAA") else "BBB"))
    go("not-a-token")
    u.disabled = True
    db_session.commit()
    go(good)


def test_forgot_rate_limit(anon_client):
    ratelimit.reset()
    for _ in range(ratelimit.PER_EMAIL):
        assert anon_client.post("/api/auth/forgot", json={"email": "t@x.co"}).status_code == 202
    assert anon_client.post("/api/auth/forgot", json={"email": "t@x.co"}).status_code == 429
