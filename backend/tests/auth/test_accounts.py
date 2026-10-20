"""M6 accounts: creation codes, join tokens, sign-up, join, workspace credits, mailer."""

from __future__ import annotations

import logging
import smtplib
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from app.api.deps import get_app_settings
from app.auth import passwords, ratelimit
from app.db.models import CreationCode, JoinToken, UserAccount
from app.services import access_codes, mailer, workspaces
from tests.api.auth_helpers import login_as

pytestmark = pytest.mark.integration

PW = "a-long-password"
GENERIC = "invalid or expired code"


def _signup(c, email, mode, code, pw=PW):
    return c.post(
        "/api/auth/signup",
        json={"email": email, "display_name": "New", "password": pw, "mode": mode, "code": code},
    )


def _new_code(client, **kw):
    r = client.post("/api/admin/creation-codes", json={"label": "friend", **kw})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def sent(monkeypatch, app, api_settings):
    """SMTP configured, the mailer stubbed: the list collects what would be sent."""
    cfg = api_settings.model_copy(
        update={"smtp_username": "me@gmail.com", "smtp_password": SecretStr("pw")}
    )
    app.dependency_overrides[get_app_settings] = lambda: cfg
    out: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        mailer,
        "send_async",
        lambda s, to, sub, text, html=None: out.append((to, sub, text)) or True,
    )
    return out


def test_creation_code_lifecycle(client, db_session):
    made = _new_code(client)
    assert len(made["code"]) >= 20 and made["status"] == "active" and made["max_uses"] == 1
    listed = client.get("/api/admin/creation-codes").json()
    assert "code" not in listed[0] and listed[0]["uses"] == 0
    row = db_session.get(CreationCode, made["id"])
    assert row.code_hash == access_codes.hash_secret(made["code"]) != made["code"]
    assert made["code"] not in str(listed)
    # max uses: the second sign-up fails
    assert _signup(client, "a@x.co", "create", made["code"]).status_code == 201
    login_as(client, "a@x.co", PW)  # new account, not the superadmin
    assert _signup(client, "b@x.co", "create", made["code"]).status_code == 400


def test_code_expiry_and_revoke(client, db_session):
    made = _new_code(client, max_uses=5)
    row = db_session.get(CreationCode, made["id"])
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    r = _signup(client, "a@x.co", "create", made["code"])
    assert r.status_code == 400 and r.json()["error"]["message"] == GENERIC
    other = _new_code(client)
    assert (
        client.post(f"/api/admin/creation-codes/{other['id']}/revoke").json()["status"] == "revoked"
    )
    assert _signup(client, "a@x.co", "create", other["code"]).status_code == 400
    assert client.post("/api/admin/creation-codes/not-a-uuid/revoke").status_code == 404


def test_signup_create_then_workspace_admin_sees_only_theirs(client, db_session):
    workspaces.create_workspace(db_session, "other", "Other", is_demo=False)
    made = _new_code(client)
    r = _signup(client, "New@x.co", "create", made["code"])
    assert r.status_code == 201
    me = r.json()
    assert me["user"]["workspace_credits"] == 1 and not me["user"]["is_admin"]
    assert me["memberships"] == []
    c = client  # now signed in as the new person (cookie set by signup)
    assert c.post("/api/workspaces", json={"slug": "mine", "name": "Mine"}).status_code == 201
    assert c.get("/api/auth/me").json()["user"]["workspace_credits"] == 0
    assert [m["role"] for m in c.get("/api/auth/me").json()["memberships"]] == ["admin"]
    assert [w["slug"] for w in c.get("/api/workspaces").json()] == ["mine"]
    assert c.get("/api/w/other/users").status_code == 404
    # no credit left: a second workspace is refused, and the credit cannot be replayed
    assert c.post("/api/workspaces", json={"slug": "two", "name": "Two"}).status_code == 403
    assert c.get("/api/admin/creation-codes").status_code == 403


def test_credit_kept_when_creation_fails(client, db_session):
    workspaces.create_workspace(db_session, "taken", "Taken", is_demo=False)
    _signup(client, "a@x.co", "create", _new_code(client)["code"])
    assert client.post("/api/workspaces", json={"slug": "taken", "name": "T"}).status_code == 409
    assert client.get("/api/auth/me").json()["user"]["workspace_credits"] == 1


def test_plain_member_cannot_create_workspace(client, make_member, db_session):
    workspaces.create_workspace(db_session, "w1", "W1", is_demo=False)
    m = make_member("w1")
    login_as(client, m.email, m.password)
    assert client.post("/api/workspaces", json={"slug": "x1", "name": "X"}).status_code == 403


def test_join_token_lifecycle_and_signup_join(client, db_session):
    workspaces.create_workspace(db_session, "w1", "W1", is_demo=False)
    workspaces.create_workspace(db_session, "w2", "W2", is_demo=False)
    r = client.post("/api/w/w1/join-tokens", json={"role": "rep", "label": "team", "max_uses": 2})
    assert r.status_code == 201
    tok = r.json()
    assert tok["link"].endswith(f"/signup?token={tok['token']}") and tok["email_queued"] is False
    row = db_session.get(JoinToken, tok["id"])
    assert row.token_hash == access_codes.hash_secret(tok["token"]) != tok["token"]
    assert "token" not in client.get("/api/w/w1/join-tokens").json()[0]
    assert _signup(client, "rep@x.co", "join", tok["token"]).status_code == 201
    me = client.get("/api/auth/me").json()
    assert [(m["workspace_slug"], m["role"]) for m in me["memberships"]] == [("w1", "rep")]
    assert me["user"]["workspace_credits"] == 0
    assert [w["slug"] for w in client.get("/api/workspaces").json()] == ["w1"]
    assert client.get("/api/w/w2/users").status_code == 404
    assert client.post("/api/w/w1/join-tokens", json={"label": "x"}).status_code == 403  # a rep


def test_join_token_expiry_revoke_max_uses(client, db_session):
    workspaces.create_workspace(db_session, "w1", "W1", is_demo=False)
    t = client.post("/api/w/w1/join-tokens", json={"label": "a"}).json()
    row = db_session.get(JoinToken, t["id"])
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    assert _signup(client, "a@x.co", "join", t["token"]).status_code == 400
    t2 = client.post("/api/w/w1/join-tokens", json={"label": "b"}).json()
    assert client.post(f"/api/w/w1/join-tokens/{t2['id']}/revoke").json()["status"] == "revoked"
    assert _signup(client, "a@x.co", "join", t2["token"]).status_code == 400
    assert (
        client.post("/api/w/w1/join-tokens", json={"label": "c", "max_uses": 51}).status_code == 422
    )
    t3 = client.post("/api/w/w1/join-tokens", json={"label": "d"}).json()
    assert _signup(client, "a@x.co", "join", t3["token"]).status_code == 201
    assert _signup(client, "b@x.co", "join", t3["token"]).status_code == 400  # used up


def test_signup_generic_errors_and_modes_do_not_mix(client, db_session):
    workspaces.create_workspace(db_session, "w1", "W1", is_demo=False)
    code = _new_code(client)["code"]
    tok = client.post("/api/w/w1/join-tokens", json={"label": "a", "max_uses": 5}).json()["token"]
    existing = client.get("/api/auth/me").json()["user"]["email"]
    bodies = []
    for email, mode, secret in (
        ("new@x.co", "create", "wrong-code-value"),
        (existing, "create", code),  # existing email, valid code
        (existing, "join", tok),
        ("new@x.co", "join", code),  # a creation code is not a join token
        ("new@x.co", "create", tok),
    ):
        r = _signup(client, email, mode, secret)
        assert r.status_code == 400
        bodies.append(r.json())
    assert all(b == bodies[0] for b in bodies) and bodies[0]["error"]["message"] == GENERIC
    # the failed attempts did not use up the valid code
    assert db_session.query(CreationCode).one().uses == 0
    assert _signup(client, "new@x.co", "create", code, pw="short").status_code == 422
    assert _signup(client, "new@x.co", "create", code, pw="").status_code == 422  # never empty


def test_signup_rate_limit(anon_client):
    ratelimit.reset()
    for _ in range(ratelimit.PER_EMAIL):
        assert _signup(anon_client, "t@x.co", "create", "nope-nope").status_code == 400
    assert _signup(anon_client, "t@x.co", "create", "nope-nope").status_code == 429
    ratelimit.reset()


def test_join_existing_account(client, make_member, db_session):
    workspaces.create_workspace(db_session, "w1", "W1", is_demo=False)
    workspaces.create_workspace(db_session, "w2", "W2", is_demo=False)
    tok = client.post("/api/w/w2/join-tokens", json={"role": "admin", "label": "a"}).json()["token"]
    m = make_member("w1")
    login_as(client, m.email, m.password)
    r = client.post("/api/auth/join", json={"token": tok})
    assert r.status_code == 200
    assert {(x["workspace_slug"], x["role"]) for x in r.json()["memberships"]} == {
        ("w1", "rep"),
        ("w2", "admin"),
    }
    bad = client.post("/api/auth/join", json={"token": "nonsense-token"})
    assert bad.status_code == 400 and bad.json()["error"]["message"] == GENERIC


def test_join_already_member_is_generic_and_free(client, make_member, db_session):
    workspaces.create_workspace(db_session, "w1", "W1", is_demo=False)
    tok = client.post("/api/w/w1/join-tokens", json={"label": "a"}).json()["token"]
    m = make_member("w1")
    login_as(client, m.email, m.password)
    r = client.post("/api/auth/join", json={"token": tok})
    assert r.status_code == 400 and r.json()["error"]["message"] == GENERIC
    assert db_session.query(JoinToken).one().uses == 0


def test_workspace_admin_boundaries(client, make_member, db_session):
    workspaces.create_workspace(db_session, "w1", "W1", is_demo=False)
    workspaces.create_workspace(db_session, "w2", "W2", is_demo=False)
    m = make_member("w1", role="admin")
    login_as(client, m.email, m.password)
    assert (
        client.post("/api/w/w1/join-tokens", json={"role": "admin", "label": "a"}).status_code
        == 201
    )
    assert client.post("/api/w/w2/join-tokens", json={"label": "a"}).status_code == 404
    assert client.get("/api/w/w2/join-tokens").status_code == 404
    assert client.post("/api/admin/creation-codes", json={"label": "a"}).status_code == 403
    assert client.get("/api/admin/creation-codes").status_code == 403


def test_cannot_revoke_other_workspace_token(client, make_member, db_session):
    workspaces.create_workspace(db_session, "w1", "W1", is_demo=False)
    workspaces.create_workspace(db_session, "w2", "W2", is_demo=False)
    t = client.post("/api/w/w2/join-tokens", json={"label": "a"}).json()
    m = make_member("w1", role="admin")
    login_as(client, m.email, m.password)
    assert client.post(f"/api/w/w1/join-tokens/{t['id']}/revoke").status_code == 404


def test_status_has_signup_enabled(anon_client):
    assert anon_client.get("/api/auth/status").json()["signup_enabled"] is True


# --- mailer -------------------------------------------------------------------------------


def test_forgot_sends_one_email(anon_client, db_session, sent):
    db_session.add(
        UserAccount(email="a@x.co", display_name="A", password_hash=passwords.hash_password(PW))
    )
    db_session.commit()
    anon_client.post("/api/auth/forgot", json={"email": "a@x.co"})
    anon_client.post("/api/auth/forgot", json={"email": "nobody@x.co"})
    assert len(sent) == 1 and sent[0][0] == "a@x.co"
    assert "http://127.0.0.1:8800/reset?token=" in sent[0][2]


def test_forgot_without_smtp_sends_nothing(anon_client, db_session, monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(mailer, "send_async", lambda *a, **k: calls.append(a))
    db_session.add(
        UserAccount(email="a@x.co", display_name="A", password_hash=passwords.hash_password(PW))
    )
    db_session.commit()
    caplog.set_level(logging.WARNING)
    assert anon_client.post("/api/auth/forgot", json={"email": "a@x.co"}).status_code == 202
    assert calls == [] and "reset?token=" in caplog.text  # local mode only


def test_join_token_email(client, db_session, sent):
    workspaces.create_workspace(db_session, "w1", "W1", is_demo=False)
    r = client.post("/api/w/w1/join-tokens", json={"label": "a", "email_to": "friend@x.co"})
    assert r.json()["email_queued"] is True
    assert sent[0][0] == "friend@x.co" and r.json()["link"] in sent[0][2]
    bad = client.post("/api/w/w1/join-tokens", json={"label": "a", "email_to": "a@x.co,b@x.co"})
    assert bad.status_code == 422


def _cfg(app, api_settings, **kw):
    cfg = api_settings.model_copy(update=kw)
    app.dependency_overrides[get_app_settings] = lambda: cfg


def test_invite_email_caps(client, db_session, sent, app, api_settings):
    workspaces.create_workspace(db_session, "w1", "W1", is_demo=False)
    _cfg(
        app,
        api_settings,
        smtp_username="me@gmail.com",
        smtp_password=SecretStr("pw"),
        invite_emails_per_user_per_day=2,
    )
    for _ in range(2):
        r = client.post("/api/w/w1/join-tokens", json={"label": "a", "email_to": "f@x.co"})
        assert r.status_code == 201
    r = client.post("/api/w/w1/join-tokens", json={"label": "a", "email_to": "f@x.co"})
    assert r.status_code == 429 and "@" not in r.text
    assert client.post("/api/w/w1/join-tokens", json={"label": "a"}).status_code == 201
    assert len(sent) == 2


def test_invite_email_workspace_cap(client, db_session, sent, app, api_settings):
    workspaces.create_workspace(db_session, "w1", "W1", is_demo=False)
    _cfg(
        app,
        api_settings,
        smtp_username="me@gmail.com",
        smtp_password=SecretStr("pw"),
        invite_emails_per_workspace_per_day=1,
    )
    body = {"label": "a", "email_to": "f@x.co"}
    assert client.post("/api/w/w1/join-tokens", json=body).status_code == 201
    assert client.post("/api/w/w1/join-tokens", json=body).status_code == 429


def test_active_join_token_cap(client, db_session, app, api_settings):
    workspaces.create_workspace(db_session, "w1", "W1", is_demo=False)
    _cfg(app, api_settings, join_tokens_max_active=2)
    ids = [
        client.post("/api/w/w1/join-tokens", json={"label": "a"}).json()["id"] for _ in range(2)
    ]
    assert client.post("/api/w/w1/join-tokens", json={"label": "a"}).status_code == 409
    client.post(f"/api/w/w1/join-tokens/{ids[0]}/revoke")
    assert client.post("/api/w/w1/join-tokens", json={"label": "a"}).status_code == 201


def test_signup_kill_switch(anon_client, app, api_settings):
    _cfg(app, api_settings, signup_enabled=False)
    assert anon_client.get("/api/auth/status").json()["signup_enabled"] is False
    r = _signup(anon_client, "a@x.co", "create", "whatever")
    assert r.status_code == 403 and "sign-up is closed" in r.text


def test_forgot_hosted_without_smtp_logs_no_link(
    anon_client, db_session, app, api_settings, caplog
):
    _cfg(app, api_settings, public_origin="https://df.example.run.app")
    db_session.add(
        UserAccount(email="a@x.co", display_name="A", password_hash=passwords.hash_password(PW))
    )
    db_session.commit()
    caplog.set_level(logging.WARNING)
    anon_client.post("/api/auth/forgot", json={"email": "a@x.co"})
    assert "a@x.co" not in caplog.text and "token" not in caplog.text


def test_mailer_pool_and_hourly_cap(api_settings, monkeypatch, caplog):
    sent_to = []
    monkeypatch.setattr(mailer, "send", lambda s, to, *a: sent_to.append(to))
    mailer._sent_at.clear()
    monkeypatch.setattr(mailer, "MAX_PER_HOUR", 2)
    caplog.set_level(logging.WARNING)
    results = [mailer.send_async(api_settings, "x@x.co", "s", "t") for _ in range(3)]
    mailer._executor.shutdown(wait=True)
    mailer._executor = type(mailer._executor)(max_workers=2)
    mailer._sent_at.clear()
    assert results == [True, True, False] and len(sent_to) == 2
    assert "x@x.co" not in caplog.text


def test_mailer_smtp_flow_and_no_secret_in_logs(api_settings, monkeypatch, caplog):
    cfg = api_settings.model_copy(
        update={"smtp_username": "me@gmail.com", "smtp_password": SecretStr("s3cret-app-pw")}
    )
    log: list[str] = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            log.append(f"connect {host}:{port} t={timeout}")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context):
            log.append("starttls")

        def login(self, u, p):
            log.append("login")

        def send_message(self, msg):
            log.append(f"send {msg['To']} {msg['From']}")

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    assert mailer.send(cfg, "x@y.co", "Hi", "text") is True
    assert log == [
        "connect smtp.gmail.com:587 t=10",
        "starttls",
        "login",
        "send x@y.co DataForce <me@gmail.com>",
    ]

    def boom(*a, **k):
        raise smtplib.SMTPAuthenticationError(535, b"bad s3cret-app-pw")

    monkeypatch.setattr(smtplib, "SMTP", boom)
    caplog.set_level(logging.DEBUG)
    assert mailer.send(cfg, "x@y.co", "Hi", "text") is False
    assert "s3cret-app-pw" not in caplog.text and "s3cret-app-pw" not in repr(cfg)


def test_mailer_refuses_header_injection_and_multiple_recipients(api_settings):
    cfg = api_settings.model_copy(
        update={"smtp_username": "me@gmail.com", "smtp_password": SecretStr("pw")}
    )
    for to in ("a@x.co\nBcc: b@x.co", "a@x.co, b@x.co", "a@x.co;b@x.co"):
        assert mailer.send(cfg, to, "Hi", "t") is False
    assert mailer.send(cfg, "a@x.co", "Hi\nBcc: b@x.co", "t") is False


def test_mailer_off_returns_false(api_settings):
    assert mailer.is_configured(api_settings) is False
    assert mailer.send(api_settings, "a@x.co", "Hi", "t") is False
