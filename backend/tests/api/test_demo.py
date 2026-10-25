"""The public demo (docs/M6-ACCOUNTS-ADMIN-CONTRACT.md section E): start, switch, guardrails, the
visitor's own AI key, the nightly swap. Every path here is reachable by anyone on the internet."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.api.routes.ai import get_chat_factory
from app.auth import demo
from app.db.models import (
    Account,
    LlmCredential,
    Membership,
    UserAccount,
    UserSession,
    Workspace,
)
from app.demo.reset import reset_demo
from app.domain.schemas import UserIn
from app.llm.fake import FakeLLM
from app.services import demo_logins, llm_settings, user_accounts, users, workspaces
from app.services.errors import InvalidInputError
from tests.api.auth_helpers import login_as

pytestmark = pytest.mark.integration

KEY = "AIzaSyDEMO-VISITOR-0123456789abcdefgh"
BLOCKED = "not available in the demo"


@pytest.fixture(autouse=True)
def _fresh_limits():
    demo.reset_limits()
    yield
    demo.reset_limits()


@pytest.fixture
def demo_ws(session_factory):
    """A demo workspace "test-data" with two CRM users who have demo accounts."""
    with session_factory() as s:
        ws = workspaces.create_workspace(s, "test-data", "Test data (synthetic)", is_demo=True)
        for name, mail in (("Ann Rep", "ann@x.test"), ("Bob Rep", "bob@x.test")):
            users.create_user(s, ws.id, UserIn(display_name=name, email=mail, role="user"))
        s.commit()
        demo_logins.backfill_logins(s, "test-data")
        s.commit()
    return "/api/w/test-data"


def start(c, who=None):
    return c.post("/api/auth/demo", json={} if who is None else {"as": who})


def identities(c):
    r = c.get("/api/auth/demo/identities")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def visitor(anon_client, demo_ws):
    r = start(anon_client)
    assert r.status_code == 200, r.text
    return anon_client


def put_key(c, key=KEY, **kw):
    body = {"provider": "gemini", "model": "gemini-2.5-flash", "api_key": key, **kw}
    return c.put("/api/auth/demo/ai-key", json=body)


# --- start and switch ---------------------------------------------------------------------------
def test_status_demo_available(anon_client, session_factory, demo_ws):
    assert anon_client.get("/api/auth/status").json()["demo_available"] is True
    with session_factory() as s:
        s.get(
            Workspace, s.scalar(select(Workspace.id).where(Workspace.slug == "test-data"))
        ).is_demo = False
        s.commit()
    assert anon_client.get("/api/auth/status").json()["demo_available"] is False


def test_status_demo_not_available_without_workspace(anon_client):
    assert anon_client.get("/api/auth/status").json()["demo_available"] is False
    assert start(anon_client).status_code == 404


def test_start_as_admin(visitor, session_factory):
    me = visitor.get("/api/auth/me").json()
    assert me["user"]["is_demo"] is True and me["user"]["is_admin"] is False
    assert [(m["workspace_slug"], m["role"]) for m in me["memberships"]] == [("test-data", "admin")]
    with session_factory() as s:
        row = s.scalars(select(UserSession)).one()
        user = s.get(UserAccount, row.user_account_id)
        assert row.is_demo and user.is_demo and user.password_hash is None
        assert row.expires_at - row.created_at <= timedelta(hours=4, seconds=5)
    assert visitor.get("/api/w/test-data/accounts").status_code == 200  # fully usable


def test_identities_and_switch_carries_ai_key(visitor, session_factory):
    ids = identities(visitor)
    assert ids[0] == {"as": "admin", "label": "Demo admin", "role": "admin"}
    reps = [i for i in ids if i["role"] == "rep"]
    assert {r["label"] for r in reps} == {"Ann Rep", "Bob Rep"}
    assert put_key(visitor).status_code == 200
    ann = next(r for r in reps if r["label"] == "Ann Rep")
    r = start(visitor, ann["as"])
    assert r.status_code == 200
    me = r.json()
    assert me["user"]["is_demo"] and me["memberships"][0]["app_user_name"] == "Ann Rep"
    assert me["memberships"][0]["role"] == "rep"
    assert visitor.get("/api/auth/demo/ai-key").json() == {
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "set": True,
    }
    with session_factory() as s:  # the old session is gone, only one is left
        assert s.scalar(select(func.count()).select_from(UserSession)) == 1
    assert start(visitor, "admin").json()["memberships"][0]["role"] == "admin"


def test_switch_never_reaches_other_accounts(visitor, session_factory, make_member):
    with session_factory() as s:
        other = workspaces.create_workspace(s, "other", "Other", is_demo=True)
        stranger = users.create_user(
            s, other.id, UserIn(display_name="Eve", email="e@x.test", role="user")
        )
        # a real person with a password in the demo workspace, linked to a CRM user
        ws = workspaces.get_workspace_by_slug(s, "test-data")
        real_au = users.create_user(
            s, ws.id, UserIn(display_name="Real Person", email="r@x.test", role="user")
        )
        s.commit()
        stranger_id, real_id = stranger.id, real_au.id
    m = make_member("test-data", role="rep", app_user_id=real_id)
    with session_factory() as s:  # password-less like a rep, but not a demo account
        assert s.get(UserAccount, m.user_id).is_demo is False
    # a demo account of another workspace
    with session_factory() as s:
        acc = user_accounts.create_account(s, "eve@other.demo", "Eve", None, is_demo=True)
        user_accounts.add_membership(s, acc, other, role="rep", app_user_id=stranger_id)
        s.commit()
    for who in (str(real_id), str(stranger_id), str(uuid.uuid4()), "nope", "../x"):
        r = start(visitor, who)
        assert r.status_code in (404, 422), (who, r.status_code)
    assert visitor.get("/api/auth/me").json()["user"]["is_demo"] is True
    assert [x["label"] for x in identities(visitor)].count("Real Person") == 0


def test_non_demo_session_cannot_start_or_switch(client, demo_ws):
    r = start(client)
    assert r.status_code == 403
    assert client.get("/api/auth/demo/identities").status_code == 403
    assert client.get("/api/auth/demo/ai-key").status_code == 403
    assert put_key(client).status_code == 403
    assert client.delete("/api/auth/demo/ai-key").status_code == 403


def test_member_session_cannot_switch(anon_client, demo_ws, make_member):
    m = make_member("test-data", role="admin")
    login_as(anon_client, m.email, m.password)
    assert start(anon_client).status_code == 403


def test_demo_accounts_cannot_sign_in_with_password(anon_client, demo_ws, session_factory):
    start(anon_client)
    anon_client.cookies.clear()
    with session_factory() as s:
        emails = list(s.scalars(select(UserAccount.email).where(UserAccount.is_demo.is_(True))))
    assert len(emails) == 3
    for email in emails:
        for pw in ("", "x" * 12):
            r = anon_client.post("/api/auth/login", json={"email": email, "password": pw})
            assert r.status_code == 401
    r = anon_client.post("/api/auth/forgot", json={"email": emails[0]})
    assert r.status_code == 202
    r = anon_client.post("/api/auth/reset", json={"token": "abc", "password": "long-enough-pw"})
    assert r.status_code == 400
    with session_factory() as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(UserAccount)
                .where(UserAccount.is_demo.is_(True), UserAccount.password_hash.is_not(None))
            )
            == 0
        )


def test_start_rate_limit(anon_client, demo_ws):
    for _ in range(demo.STARTS_PER_HOUR):
        anon_client.cookies.clear()
        assert start(anon_client).status_code == 200
    anon_client.cookies.clear()
    assert start(anon_client).status_code == 429


def test_demo_session_ends_after_four_hours_and_does_not_slide(visitor, session_factory):
    with session_factory() as s:
        row = s.scalars(select(UserSession)).one()
        row.last_seen_at = datetime.now(UTC) - timedelta(minutes=5)
        before = row.expires_at
        s.commit()
    assert visitor.get("/api/auth/me").status_code == 200
    with session_factory() as s:
        assert s.scalars(select(UserSession)).one().expires_at == before  # no sliding
        row = s.scalars(select(UserSession)).one()
        row.created_at = datetime.now(UTC) - timedelta(hours=4, minutes=1)
        s.commit()
    assert visitor.get("/api/auth/me").status_code == 401


def test_logout_deletes_session_and_key(visitor, session_factory):
    assert put_key(visitor).status_code == 200
    assert visitor.post("/api/auth/logout").status_code == 204
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(UserSession)) == 0


# --- guardrails ---------------------------------------------------------------------------------
ID = "00000000-0000-0000-0000-000000000001"
BLOCKED_ROUTES = [
    ("post", "/api/admin/creation-codes", {"label": "x", "max_uses": 1, "expires_in_days": 7}),
    ("post", f"/api/admin/creation-codes/{ID}/revoke", None),
    ("post", "/api/w/test-data/join-tokens", {"role": "rep", "expires_in_days": 7}),
    ("post", f"/api/w/test-data/join-tokens/{ID}/revoke", None),
    ("post", "/api/w/test-data/members", {"email": "a@b.co", "display_name": "A", "password": ""}),
    ("patch", f"/api/w/test-data/members/{ID}", {"role": "admin"}),
    ("post", f"/api/w/test-data/members/{ID}/password", {"password": "long-enough-pw"}),
    ("post", f"/api/w/test-data/members/{ID}/disable", None),
    ("post", f"/api/w/test-data/members/{ID}/enable", None),
    ("delete", f"/api/w/test-data/members/{ID}", None),
    ("post", "/api/w/test-data/connectors/tamtam/connect", {}),
    ("post", "/api/w/test-data/connectors/tamtam/check", None),
    ("delete", "/api/w/test-data/connectors/tamtam", None),
    ("put", "/api/w/test-data/mailbox/gmail/client", {"client_id": "a", "client_secret": "b"}),
    ("post", "/api/w/test-data/mailbox/gmail/connect", {}),
    ("post", "/api/w/test-data/mailbox/sync", None),
    ("delete", "/api/w/test-data/mailbox/gmail", None),
    ("post", f"/api/w/test-data/mailbox/messages/{ID}/link", {}),
    ("post", f"/api/w/test-data/mailbox/messages/{ID}/ignore", None),
    ("post", f"/api/w/test-data/mailbox/messages/{ID}/unlink", None),
    ("post", "/api/w/test-data/connections", {"name": "x", "kind": "postgres"}),
    ("patch", f"/api/w/test-data/connections/{ID}", {"name": "x"}),
    ("delete", f"/api/w/test-data/connections/{ID}", None),
    ("post", f"/api/w/test-data/connections/{ID}/test", None),
    ("put", "/api/w/test-data/ai", {"provider": "gemini", "model": "m", "api_key": KEY}),
    ("put", "/api/w/test-data/ai/meeting-org", {"enabled": True}),
    ("delete", "/api/w/test-data/ai", None),
    ("post", "/api/w/test-data/ai/test", None),
    ("post", "/api/workspaces", {"slug": "mine", "name": "Mine", "kind": "real"}),
    ("delete", "/api/workspaces/test-data", None),
    ("put", "/api/admin/limits/db_quota_mb", {"value": 1}),
    ("put", "/api/w/test-data/admin/limits/db_quota_mb", {"value": 1}),
    ("put", "/api/admin/model-prices", {}),
    ("delete", f"/api/admin/model-prices/{ID}", None),
    ("post", "/api/auth/join", {"token": "abc"}),
]


@pytest.mark.parametrize(("method", "path", "body"), BLOCKED_ROUTES)
def test_blocked_routes_refuse_a_demo_session(visitor, method, path, body):
    r = getattr(visitor, method)(path, **({"json": body} if body is not None else {}))
    assert r.status_code == 403, (path, r.status_code, r.text)
    assert BLOCKED in r.text


def test_blocked_routes_cover_every_listed_decorator(app):
    """Every route that carries the NotDemo dependency is in the list above (and the reverse)."""
    guarded = set()
    for route in app.routes:
        deps = getattr(route, "dependencies", None) or []
        if any(getattr(d.dependency, "__name__", "") == "require_not_demo" for d in deps):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                guarded.add((method.lower(), route.path))
    listed = set()
    for method, path, _ in BLOCKED_ROUTES:
        for g_method, g_path in guarded:
            if g_method == method and _matches(g_path, path):
                listed.add((g_method, g_path))
    assert listed == guarded, sorted(guarded - listed)


def _matches(template: str, path: str) -> bool:
    t, p = template.strip("/").split("/"), path.strip("/").split("/")
    return len(t) == len(p) and all(
        a == b or (a.startswith("{") and a.endswith("}")) for a, b in zip(t, p, strict=True)
    )


def test_blocked_routes_work_for_a_normal_admin(client, demo_ws):
    # the same guard must not stop a real superadmin
    assert client.get("/api/w/test-data/members").status_code == 200
    assert (
        client.post(
            "/api/admin/creation-codes", json={"label": "x", "max_uses": 1, "expires_in_days": 7}
        ).status_code
        == 201
    )


def test_upload_limits(visitor):
    big = io.BytesIO(b"a,b\n" + b"1,2\n" * (700 * 1024))
    r = visitor.post("/api/w/test-data/files", files={"file": ("big.csv", big, "text/csv")})
    assert r.status_code == 413
    codes = []
    for i in range(demo.UPLOADS_PER_DAY):  # the big one is stopped before it counts
        small = io.BytesIO(b"a,b\n1,2\n")
        r = visitor.post("/api/w/test-data/files", files={"file": (f"s{i}.csv", small, "text/csv")})
        codes.append(r.status_code)
    assert 429 not in codes
    small = io.BytesIO(b"a,b\n1,2\n")
    r = visitor.post("/api/w/test-data/files", files={"file": ("z.csv", small, "text/csv")})
    assert r.status_code == 429


# --- AI: the visitor's own key only ---------------------------------------------------------------
def test_ai_key_lifecycle_and_never_leaks(visitor, session_factory, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    assert visitor.get("/api/auth/demo/ai-key").json() == {
        "provider": None,
        "model": None,
        "set": False,
    }
    r = put_key(visitor)
    assert r.status_code == 200 and r.json()["set"] is True
    assert KEY not in r.text and "api_key" not in r.text
    assert KEY not in visitor.get("/api/auth/demo/ai-key").text
    assert put_key(visitor, key="short").status_code in (400, 422)
    assert put_key(visitor, key="has space in the key 0123456789").status_code in (400, 422)
    assert put_key(visitor, provider="openai").status_code == 422
    with session_factory() as s:
        sealed = s.scalars(select(UserSession)).one().llm_key_enc
        assert sealed and KEY not in sealed
        assert s.scalar(select(func.count()).select_from(LlmCredential)) == 0
    assert KEY not in caplog.text
    assert visitor.delete("/api/auth/demo/ai-key").status_code == 204
    assert visitor.get("/api/auth/demo/ai-key").json()["set"] is False


def make_fake(app):
    seen = {}

    def factory(provider, *, api_key, model, settings, usage):
        llm = FakeLLM(usage=usage)
        llm.model = model
        llm.register_text(lambda s, m, **kw: "fine [F1]")
        seen["key"], seen["provider"] = api_key, provider
        return llm

    app.dependency_overrides[get_chat_factory] = lambda: factory
    return seen


def test_assistant_uses_only_the_session_key(visitor, app, session_factory):
    seen = make_fake(app)
    co = visitor.post("/api/w/test-data/companies", json={"name": "Acme"}).json()
    body = {"scope": {"kind": "company", "id": co["id"]}, "question": "hi", "history": []}
    # the workspace has its own stored key: a demo session must still not use it
    with session_factory() as s:
        ws = workspaces.get_workspace_by_slug(s, "test-data")
        llm_settings.save_settings(
            s,
            ws.id,
            provider="gemini",
            model="m",
            api_key="WORKSPACE-KEY-0123456789abcdef",
            settings=app.dependency_overrides[
                __import__("app.api.deps", fromlist=["get_app_settings"]).get_app_settings
            ](),
        )
        s.commit()
    r = visitor.post("/api/w/test-data/assistant/ask", json=body)
    assert r.status_code == 409 and "Add your own key to try AI in the demo" in r.text
    assert seen == {}
    assert put_key(visitor).status_code == 200
    r = visitor.post("/api/w/test-data/assistant/ask", json=body)
    assert r.status_code == 200, r.text
    assert seen["key"] == KEY and seen["provider"] == "gemini"
    # the workspace row is untouched, the session key never reached it
    with session_factory() as s:
        cred = s.scalars(select(LlmCredential)).one()
        assert cred.model == "m"
    # another visitor has no key
    visitor.cookies.clear()
    assert start(visitor).status_code == 200
    assert visitor.post("/api/w/test-data/assistant/ask", json=body).status_code == 409


def test_get_credential_without_demo_marker_is_the_workspace_one(db_session, ws_id, api_settings):
    llm_settings.save_settings(
        db_session, ws_id, provider="gemini", model="m", api_key=KEY, settings=api_settings
    )
    assert llm_settings.get_credential(db_session, ws_id).model == "m"
    db_session.info[llm_settings.DEMO_INFO_KEY] = uuid.uuid4()  # a demo session with no row
    assert llm_settings.get_credential(db_session, ws_id) is None
    with pytest.raises(Exception, match="Add your own key"):
        llm_settings.require_credential(db_session, ws_id)


# --- onboarding (E5) ------------------------------------------------------------------------------
def test_credit_holder_cannot_create_a_test_workspace(anon_client, session_factory):
    with session_factory() as s:
        acc = user_accounts.create_account(
            s,
            "cred@x.test",
            "Cred",
            __import__("app.auth.passwords", fromlist=["x"]).hash_password("a-long-password"),
        )
        acc.workspace_credits = 1
        s.commit()
    login_as(anon_client, "cred@x.test", "a-long-password")
    r = anon_client.post("/api/workspaces", json={"slug": "tst", "name": "T", "kind": "test"})
    assert r.status_code == 403
    r = anon_client.post("/api/workspaces", json={"slug": "real", "name": "R", "kind": "real"})
    assert r.status_code == 201  # the credit was not spent by the refused request


def test_reserved_demo_address_and_demo_membership_rules(session_factory):
    with session_factory() as s:
        with pytest.raises(InvalidInputError):
            user_accounts.create_account(s, "demo-admin@demo.invalid", "X", None)
        real = workspaces.create_workspace(s, "real-ws", "Real", is_demo=False)
        acc = user_accounts.create_account(s, "d@demo.invalid", "D", None, is_demo=True)
        with pytest.raises(InvalidInputError):
            user_accounts.add_membership(s, acc, real, role="admin")


# --- the nightly swap -----------------------------------------------------------------------------
def test_reset_swap_keeps_demo_working(anon_client, session_factory):
    steps: list[str] = []
    reset_demo(session_factory, "test-data", steps.append)  # first build: nothing to replace
    assert steps[-1] == "swapped"
    with session_factory() as s:
        ws1 = workspaces.get_workspace_by_slug(s, "test-data")
        assert ws1 is not None and ws1.is_demo
        assert workspaces.get_workspace_by_slug(s, "test-data-rebuild") is None
        ws1_id = ws1.id
    assert start(anon_client).status_code == 200
    rep = next(i for i in identities(anon_client) if i["role"] == "rep")
    assert start(anon_client, rep["as"]).status_code == 200
    rep_user = anon_client.get("/api/auth/me").json()["user"]["id"]
    assert put_key(anon_client).status_code == 200

    reset_demo(session_factory, "test-data")
    assert anon_client.get("/api/auth/me").status_code == 401  # every demo session ended
    with session_factory() as s:
        ws2 = workspaces.get_workspace_by_slug(s, "test-data")
        assert ws2.id != ws1_id and ws2.is_demo
        assert s.get(Workspace, ws1_id) is None
        assert s.scalar(select(func.count()).select_from(UserSession)) == 0
        assert (
            s.scalar(
                select(func.count()).select_from(Account).where(Account.workspace_id == ws2.id)
            )
            > 0
        )
        assert s.scalar(select(func.count()).select_from(LlmCredential)) == 0
    # the same rep account is still there, and the demo works again
    anon_client.cookies.clear()
    assert start(anon_client).status_code == 200
    new_rep = next(i for i in identities(anon_client) if i["label"] == rep["label"])
    me = start(anon_client, new_rep["as"]).json()
    assert me["user"]["id"] == rep_user
    assert me["memberships"][0]["workspace_slug"] == "test-data"
    assert anon_client.get("/api/w/test-data/accounts").status_code == 200
    with session_factory() as s:  # no duplicated demo admin or accounts
        assert (
            s.scalar(
                select(func.count())
                .select_from(UserAccount)
                .where(UserAccount.email == demo.ADMIN_EMAIL)
            )
            == 1
        )


def test_reset_refuses_a_real_workspace(session_factory):
    with session_factory() as s:
        workspaces.create_workspace(s, "precious", "Precious", is_demo=False)
        s.commit()
    with pytest.raises(InvalidInputError, match="not a test workspace"):
        reset_demo(session_factory, "precious")
    with session_factory() as s:
        assert workspaces.get_workspace_by_slug(s, "precious") is not None
        assert s.scalar(select(func.count()).select_from(Membership)) == 0


# --- write budget, size and fullness guards -----------------------------------------------------
def test_write_budget_per_hour_and_lifetime(visitor, monkeypatch):
    monkeypatch.setattr(demo, "WRITES_PER_HOUR", 3)
    for _ in range(3):
        assert visitor.post("/api/w/test-data/notes", json={}).status_code != 429
    r = visitor.post("/api/w/test-data/notes", json={})
    assert r.status_code == 429 and "Demo limit reached" in r.text
    assert visitor.get("/api/w/test-data/accounts").status_code == 200  # reads are free
    demo.reset_limits()
    monkeypatch.setattr(demo, "WRITES_PER_HOUR", 100)
    monkeypatch.setattr(demo, "WRITES_PER_SESSION", 2)
    codes = [visitor.post("/api/w/test-data/notes", json={}).status_code for _ in range(3)]
    assert codes[2] == 429 and 429 not in codes[:2]


def test_write_budget_ignores_normal_sessions(client, monkeypatch):
    monkeypatch.setattr(demo, "WRITES_PER_HOUR", 1)
    for _ in range(3):
        assert client.post("/api/w/nope/notes", json={}).status_code != 429


def test_heavy_cap_per_hour_and_concurrency(visitor, monkeypatch):
    path = "/api/w/test-data/viz/query"
    monkeypatch.setattr(demo, "HEAVY_PER_HOUR", 2)
    assert [visitor.post(path, json={}).status_code != 429 for _ in range(2)] == [True, True]
    assert visitor.post(path, json={}).status_code == 429
    assert demo._running == 0  # slots are given back
    demo.reset_limits()
    demo._running = demo.HEAVY_AT_ONCE
    r = visitor.post(path, json={})
    assert r.status_code == 429 and "busy" in r.text
    assert visitor.post("/api/w/test-data/notes", json={}).status_code != 429  # light is fine
    demo._running = 0


def test_big_body_refused_but_uploads_have_own_cap(visitor):
    r = visitor.post("/api/w/test-data/notes", json={"body": "x" * 30_000})
    assert r.status_code == 413
    big = io.BytesIO(b"a,b\n" + b"1,2\n" * 5000)  # ~20 KB file, fine for the upload route
    r = visitor.post("/api/w/test-data/files", files={"file": ("a.csv", big, "text/csv")})
    assert r.status_code != 413
    assert visitor.delete("/api/w/test-data/notes/" + str(uuid.uuid4())).status_code != 413


def test_database_full_refuses_writes(visitor, monkeypatch):
    monkeypatch.setattr(demo, "db_size", lambda db, quota: {"used_pct": 71.0})
    r = visitor.post("/api/w/test-data/notes", json={})
    assert r.status_code == 503 and "full until tonight" in r.text
    assert visitor.get("/api/w/test-data/accounts").status_code == 200
    assert start(visitor).status_code == 200  # sign-in routes still work
    calls = []
    monkeypatch.setattr(demo, "db_size", lambda db, quota: calls.append(1) or {"used_pct": 10.0})
    demo.reset_limits()
    visitor.post("/api/w/test-data/notes", json={})
    visitor.post("/api/w/test-data/notes", json={})
    assert len(calls) == 1  # cached for a minute


def test_create_user_and_registry_writes_blocked(visitor):
    r = visitor.post(
        "/api/w/test-data/users",
        json={"display_name": "Eve", "email": "eve@x.test", "role": "user"},
    )
    assert r.status_code == 403 and BLOCKED in r.text
    r = visitor.post("/api/w/test-data/companies/from-registry", json={"siren": "552100554"})
    assert r.status_code == 403
    r = visitor.post(f"/api/w/test-data/companies/{uuid.uuid4()}/refresh-registry")
    assert r.status_code == 403


def test_registry_search_budget(visitor, monkeypatch):
    monkeypatch.setattr(demo, "REGISTRY_PER_HOUR", 2)
    path = "/api/w/test-data/registry/search"
    assert [visitor.post(path, json={}).status_code for _ in range(2)] != [429, 429]
    assert visitor.post(path, json={}).status_code == 429


def test_demo_session_cannot_enter_real_workspace(visitor, session_factory):
    with session_factory() as s:
        ws = workspaces.create_workspace(s, "real", "Real", is_demo=False)
        acc = s.scalars(select(UserAccount).where(UserAccount.email == demo.ADMIN_EMAIL)).one()
        s.add(Membership(user_account_id=acc.id, workspace_id=ws.id, role="admin"))
        s.commit()
    assert visitor.get("/api/w/real/accounts").status_code == 404


def test_ensure_accounts_skips_members_of_real_workspaces(session_factory, demo_ws):
    with session_factory() as s:
        ws = workspaces.get_workspace_by_slug(s, "test-data")
        real = workspaces.create_workspace(s, "real", "Real", is_demo=False)
        acc = s.scalars(
            select(UserAccount)
            .join(Membership, Membership.user_account_id == UserAccount.id)
            .where(Membership.workspace_id == ws.id, Membership.app_user_id.is_not(None))
        ).first()
        acc.is_demo = False
        user_accounts.add_membership(s, acc, real, role="admin")
        s.flush()
        demo.ensure_accounts(s, ws)
        assert acc.is_demo is False


def test_start_key_uses_ipv6_64_and_full_table_refuses(monkeypatch):
    assert demo.address_key("2001:db8:1:2:aaaa::1") == demo.address_key("2001:db8:1:2:bbbb::9")
    assert demo.address_key("2001:db8:1:3::1") != demo.address_key("2001:db8:1:2::1")
    assert demo.address_key("203.0.113.5") == "203.0.113.5"
    monkeypatch.setattr(demo, "_MAX_KEYS", 3)
    assert all(demo.take_start(f"10.0.0.{i}") for i in range(3))
    assert demo.take_start("10.0.0.99") is False  # full: refuse the newcomer
    assert demo.take_start("10.0.0.1") is True  # existing buckets stay


def test_expired_demo_sessions_purged_on_lookup(visitor, session_factory):
    with session_factory() as s:
        admin = s.scalars(select(UserAccount).where(UserAccount.email == demo.ADMIN_EMAIL)).one()
        s.add(
            UserSession(
                user_account_id=admin.id,
                token_hash="x" * 64,
                is_demo=True,
                created_at=datetime.now(UTC) - timedelta(hours=9),
                last_seen_at=datetime.now(UTC) - timedelta(hours=9),
                expires_at=datetime.now(UTC) - timedelta(hours=5),
            )
        )
        s.commit()
    demo.reset_limits()
    assert visitor.get("/api/auth/me").status_code == 200
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(UserSession)) == 1


def test_ai_key_model_pattern(visitor):
    assert put_key(visitor, model="a/b").status_code == 422
    assert put_key(visitor, model="x" * 101).status_code == 422
    assert put_key(visitor, model="gemini-2.5-flash").status_code == 200


def test_reset_lock_blocks_second_reset(session_factory, demo_ws):
    from sqlalchemy import text

    from app.demo import reset as reset_mod

    # the test sessions share one connection (and a lock is per connection): hold it on another
    with session_factory.kw["bind"].engine.connect() as other:
        other.execute(text("SELECT pg_advisory_lock(:k)"), {"k": reset_mod.LOCK_KEY})
        try:
            assert reset_demo(session_factory, "test-data") is False
        finally:
            other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": reset_mod.LOCK_KEY})
