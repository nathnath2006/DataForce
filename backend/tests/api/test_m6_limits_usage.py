"""M6 section B: admin-editable limits, usage per user, models list, task status in_progress."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.api.routes.ai import get_chat_factory
from app.db.models import LlmCall, SettingOverrideAudit, Task, UserAccount, Workspace
from app.llm.fake import FakeLLM
from app.services import limits, llm_settings
from tests.api.auth_helpers import login_as

pytestmark = pytest.mark.integration

KEY = "AIzaSyTESTKEY-0123456789abcdefghij"


@pytest.fixture
def ws(client):
    for slug in ("a1", "a2"):
        assert client.post("/api/workspaces", json={"slug": slug, "name": slug}).status_code == 201
    return "/api/w/a1"


def _limit(rows, key):
    return next(r for r in rows if r["key"] == key)


# --- limits ----------------------------------------------------------------------------------
def test_limit_shape_and_resolution_order(client, ws, api_settings):
    rows = client.get("/api/admin/limits").json()
    row = _limit(rows, "genai_max_calls_per_day")
    assert set(row) >= {
        "key",
        "value",
        "default",
        "source",
        "min",
        "max",
        "unit",
        "description",
        "group",
    }
    assert row["source"] == "default" and row["value"] == row["default"] == 200
    # global override beats the .env default
    r = client.put("/api/admin/limits/genai_max_calls_per_day", json={"value": 50})
    assert r.status_code == 200 and r.json()["value"] == 50 and r.json()["source"] == "global"
    # workspace override beats the global one
    r = client.put(f"{ws}/admin/limits/genai_max_calls_per_day", json={"value": 20})
    assert r.json()["value"] == 20 and r.json()["source"] == "workspace"
    assert r.json()["global_value"] == 50
    other = client.get("/api/w/a2/admin/limits").json()
    assert _limit(other, "genai_max_calls_per_day")["value"] == 50  # a2 sees the global one
    # reset: back to global, then to .env
    r = client.put(f"{ws}/admin/limits/genai_max_calls_per_day", json={"value": None})
    assert r.json()["value"] == 50 and r.json()["source"] == "global"
    r = client.put("/api/admin/limits/genai_max_calls_per_day", json={"value": None})
    assert r.json()["value"] == 200 and r.json()["source"] == "default"


def test_limit_bounds_and_lower_only(client, ws):
    put = client.put
    assert (
        put("/api/admin/limits/genai_max_calls_per_day", json={"value": 50_001}).status_code == 422
    )
    assert put("/api/admin/limits/genai_max_calls_per_day", json={"value": -1}).status_code == 422
    assert put("/api/admin/limits/genai_max_calls_per_day", json={"value": 1.5}).status_code == 422
    assert put("/api/admin/limits/genai_max_calls_per_day", json={"value": True}).status_code == 422
    assert put("/api/admin/limits/nope", json={"value": 1}).status_code == 404
    assert (
        put("/api/admin/limits/gemini_api_key", json={"value": 1}).status_code == 404
    )  # not listed
    assert put("/api/admin/limits/genai_max_calls_per_day", json={"extra": 1}).status_code == 422
    put("/api/admin/limits/genai_max_calls_per_day", json={"value": 50})
    r = put(f"{ws}/admin/limits/genai_max_calls_per_day", json={"value": 51})
    assert r.status_code == 422 and "global" in r.text
    assert put(f"{ws}/admin/limits/genai_max_calls_per_day", json={"value": 50}).status_code == 200
    # lowering the global later also caps an older, higher workspace value
    put("/api/admin/limits/genai_max_calls_per_day", json={"value": 10})
    rows = client.get(f"{ws}/admin/limits").json()
    assert _limit(rows, "genai_max_calls_per_day")["value"] == 10


def test_limit_permissions(client, ws, make_member):
    admin = make_member("a1", role="admin")
    rep = make_member("a1", role="rep")
    login_as(client, rep.email, rep.password)
    assert client.get(f"{ws}/admin/limits").status_code == 403
    assert client.put(f"{ws}/admin/limits/flow_max_rows", json={"value": 2000}).status_code == 403
    login_as(client, admin.email, admin.password)
    assert client.get(f"{ws}/admin/limits").status_code == 200
    assert client.put(f"{ws}/admin/limits/flow_max_rows", json={"value": 2000}).status_code == 200
    # a workspace admin never edits the global limits, nor another workspace's
    assert client.get("/api/admin/limits").status_code == 403
    assert client.put("/api/admin/limits/flow_max_rows", json={"value": 2000}).status_code == 403
    assert client.get("/api/w/a2/admin/limits").status_code in (403, 404)
    assert client.put("/api/w/a2/admin/limits/flow_max_rows", json={"value": 2000}).status_code in (
        403,
        404,
    )


def test_limit_changes_are_audited(client, ws, db_session):
    client.put("/api/admin/limits/flow_max_rows", json={"value": 5000})
    client.put(f"{ws}/admin/limits/flow_max_rows", json={"value": 3000})
    client.put(f"{ws}/admin/limits/flow_max_rows", json={"value": None})
    rows = db_session.scalars(
        select(SettingOverrideAudit).order_by(SettingOverrideAudit.changed_at)
    ).all()
    assert [(r.workspace_id is not None, r.old_value, r.new_value) for r in rows] == [
        (False, None, 5000),
        (True, None, 3000),
        (True, 3000, None),
    ]
    assert all(r.changed_by is not None for r in rows)


def test_limits_are_applied_by_services(client, ws, db_session, api_settings):
    ws_row = db_session.scalar(select(Workspace).where(Workspace.slug == "a1"))
    client.put(f"{ws}/admin/limits/assistant_max_asks_per_hour", json={"value": 7})
    client.put(f"{ws}/admin/limits/flow_max_rows", json={"value": 1000})
    eff = limits.effective_settings(db_session, api_settings, ws_row.id)
    assert eff.assistant_max_asks_per_hour == 7 and eff.flow_max_rows == 1000
    assert api_settings.flow_max_rows == 200_000  # the original is not touched
    other = db_session.scalar(select(Workspace).where(Workspace.slug == "a2"))
    assert limits.effective_settings(db_session, api_settings, other.id).flow_max_rows == 200_000
    # the file upload service reads flow_max_rows through the limits service
    csv = "a\n" + "\n".join(str(i) for i in range(1500))
    r = client.post(f"{ws}/files", files={"file": ("big.csv", csv, "text/csv")})
    assert r.status_code == 422 and "1000" in r.text
    # overview shows the effective value
    ov = client.get(f"{ws}/admin/overview").json()["limits"]
    assert next(x for x in ov if x["name"] == "assistant_max_asks_per_hour")["value"] == 7


# --- usage ----------------------------------------------------------------------------------
def _calls(
    db,
    ws_slug,
    user_id,
    n,
    *,
    model="gemini-3.5-flash",
    tin=1000,
    tout=500,
    ok=True,
    purpose="assistant",
    age_days=0.0,
    latency=100,
):
    wid = db.scalar(select(Workspace.id).where(Workspace.slug == ws_slug))
    for i in range(n):
        db.add(
            LlmCall(
                workspace_id=wid,
                user_account_id=user_id,
                provider="gemini",
                model=model,
                purpose=purpose,
                input_tokens=tin,
                output_tokens=tout,
                latency_ms=latency + i,
                success=ok,
                created_at=datetime.now(UTC) - timedelta(days=age_days),
            )
        )
    db.commit()


def test_usage_aggregation_with_and_without_price(client, ws, db_session, make_member):
    m = make_member("a1", role="rep")
    _calls(db_session, "a1", m.user_id, 2)
    _calls(
        db_session,
        "a1",
        None,
        1,
        purpose="title_classification",
        model="gemini-2.5-flash",
        tin=100,
        tout=50,
    )
    _calls(db_session, "a1", m.user_id, 1, ok=False, age_days=40)  # outside 30 days
    r = client.get(f"{ws}/admin/usage?days=30")
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["totals"]["calls"] == 3 and u["totals"]["input_tokens"] == 2100
    assert u["totals"]["failures"] == 0 and u["totals"]["p50_latency_ms"] is not None
    assert u["totals"]["cost_eur"] is None and u["totals"]["avg_cost_per_call_eur"] is None
    assert u["totals"]["unpriced_calls"] == 3
    users = {x["name"]: x for x in u["by_user"]}
    assert users["System"]["calls"] == 1 and users["System"]["user_id"] is None
    assert users[m_name(db_session, m)]["calls"] == 2
    assert u["by_model"][0]["price_set"] is False
    assert {p["purpose"] for p in u["by_purpose"]} == {"assistant", "title_classification"}
    assert len(u["by_day"]) == 1 and u["by_day"][0]["day"] == date.today().isoformat()
    assert len(u["by_day_user"]) == 2
    assert client.get(f"{ws}/admin/usage?days=90").json()["totals"]["calls"] == 4
    assert client.get(f"{ws}/admin/usage?days=0").status_code == 422

    # a price turns the cost on: 2 calls of 1000 in / 500 out at 0.30 / 2.50 per Mtok
    r = client.put(
        "/api/admin/model-prices",
        json={
            "provider": "gemini",
            "model": "gemini-3.5-flash",
            "input_per_mtok_eur": 0.3,
            "output_per_mtok_eur": 2.5,
        },
    )
    assert r.status_code == 200, r.text
    u = client.get(f"{ws}/admin/usage?days=30").json()
    mine = next(x for x in u["by_user"] if x["user_id"] == str(m.user_id))
    assert mine["cost_eur"] == pytest.approx(2 * (1000 * 0.3 + 500 * 2.5) / 1e6)
    assert mine["avg_cost_per_call_eur"] == pytest.approx((1000 * 0.3 + 500 * 2.5) / 1e6)
    assert mine["unpriced_calls"] == 0
    assert u["by_model"][0]["price_set"] is True
    # a mixed group costs the priced calls only and says how many were left out
    assert u["totals"]["unpriced_calls"] == 1 and u["totals"]["cost_eur"] is not None
    # prices are listed and deletable by the superadmin only
    prices = client.get("/api/admin/model-prices").json()
    assert len(prices) == 1
    assert (
        client.put(
            "/api/admin/model-prices",
            json={"provider": "x", "model": "m", "input_per_mtok_eur": 1, "output_per_mtok_eur": 1},
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/admin/model-prices",
            json={
                "provider": "gemini",
                "model": "m",
                "input_per_mtok_eur": -1,
                "output_per_mtok_eur": 1,
            },
        ).status_code
        == 422
    )
    assert client.delete(f"/api/admin/model-prices/{prices[0]['id']}").status_code == 204
    assert client.get("/api/admin/model-prices").json() == []


def m_name(db, m):
    return db.get(UserAccount, m.user_id).display_name


def test_usage_isolation_and_global_split(client, ws, db_session, make_member):
    admin_a1 = make_member("a1", role="admin")
    _calls(db_session, "a1", admin_a1.user_id, 2)
    _calls(db_session, "a2", None, 5, purpose="deal_summary")
    login_as(client, admin_a1.email, admin_a1.password)
    own = client.get(f"{ws}/admin/usage").json()
    assert own["totals"]["calls"] == 2 and "by_workspace" not in own
    assert {p["purpose"] for p in own["by_purpose"]} == {"assistant"}
    assert client.get("/api/w/a2/admin/usage").status_code in (403, 404)
    assert client.get("/api/admin/usage").status_code == 403
    assert client.get("/api/admin/model-prices").status_code == 403
    assert (
        client.put(
            "/api/admin/model-prices",
            json={
                "provider": "gemini",
                "model": "m",
                "input_per_mtok_eur": 1,
                "output_per_mtok_eur": 1,
            },
        ).status_code
        == 403
    )
    # the superadmin sees every workspace, split by workspace
    rep = make_member("a2", role="rep")
    login_as(client, rep.email, rep.password)
    assert client.get("/api/w/a2/admin/usage").status_code == 403


def test_superadmin_usage_split_by_workspace(client, ws, db_session):
    _calls(db_session, "a1", None, 2)
    _calls(db_session, "a2", None, 5)
    u = client.get("/api/admin/usage?days=7").json()
    assert u["totals"]["calls"] == 7
    assert {w["slug"]: w["calls"] for w in u["by_workspace"]} == {"a1": 2, "a2": 5}


# --- attribution --------------------------------------------------------------------------------
def test_assistant_call_is_attributed_to_the_signed_in_user(
    client, ws, app, db_session, make_member
):
    def factory(provider, *, api_key, model, settings, usage):
        llm = FakeLLM(usage=usage)
        llm.model = model
        llm.register_text(lambda system, messages: "OK")
        return llm

    app.dependency_overrides[get_chat_factory] = lambda: factory
    r = client.put(
        f"{ws}/ai", json={"provider": "gemini", "model": "gemini-3.5-flash", "api_key": KEY}
    )
    assert r.status_code == 200
    me = db_session.scalar(select(UserAccount).where(UserAccount.is_admin.is_(True)))
    assert client.post(f"{ws}/ai/test").status_code == 200
    row = db_session.scalars(select(LlmCall).where(LlmCall.purpose == "connection_test")).one()
    assert row.user_account_id == me.id


def test_recorder_without_user_stays_system(db_session):
    from sqlalchemy.orm import sessionmaker

    from app.domain.schemas import LLMCallRecord
    from app.services.llm_usage import DbUsageRecorder

    wid = db_session.scalar(select(Workspace.id)) or None
    if wid is None:
        from app.services import workspaces

        wid = workspaces.create_workspace(db_session, "rec", "Rec").id
    rec = DbUsageRecorder(
        sessionmaker(bind=db_session.get_bind(), join_transaction_mode="create_savepoint"),
        workspace_id=wid,
    )
    rec.record(
        LLMCallRecord(provider="gemini", model="m", purpose="assistant", latency_ms=1, success=True)
    )
    assert db_session.scalars(select(LlmCall)).one().user_account_id is None


# --- models list ---------------------------------------------------------------------------------
def test_models_fallback_without_key(client, ws):
    r = client.get(f"{ws}/ai/models")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "fallback" and body["provider"] == "gemini"
    assert body["default"] == "gemini-3.5-flash"
    assert body["models"] == [
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-pro-preview",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
    ]
    a = client.get(f"{ws}/ai/models?provider=anthropic").json()
    assert a["models"] == llm_settings.SUGGESTED_MODELS["anthropic"] and a["source"] == "fallback"
    assert client.get(f"{ws}/ai/models?provider=openai").status_code == 422


def test_models_from_provider_cached_and_fallback_on_error(client, ws, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    llm_settings.clear_model_cache()
    calls = []

    def fetch(provider, key, settings):
        calls.append(provider)
        assert key == KEY
        return ["gemini-3.5-flash", "gemini-9-test", "gemini-9-test"]

    monkeypatch.setattr(llm_settings, "fetch_provider_models", fetch)
    client.put(f"{ws}/ai", json={"provider": "gemini", "model": "gemini-3.5-flash", "api_key": KEY})
    r = client.get(f"{ws}/ai/models").json()
    assert r["source"] == "provider" and r["models"] == ["gemini-3.5-flash", "gemini-9-test"]
    client.get(f"{ws}/ai/models")
    assert calls == ["gemini"]  # cached for an hour
    # another workspace has no key of its own: it never uses this one
    assert client.get("/api/w/a2/ai/models").json()["source"] == "fallback"
    # a failing provider call falls back, and the key stays out of logs and answers
    llm_settings.clear_model_cache()

    def boom(provider, key, settings):
        raise RuntimeError(f"401 for key {key}")

    monkeypatch.setattr(llm_settings, "fetch_provider_models", boom)
    r = client.get(f"{ws}/ai/models")
    assert r.json()["source"] == "fallback" and KEY not in r.text and KEY not in caplog.text
    llm_settings.clear_model_cache()


def test_gemini_3_5_options():
    from app.config import Settings
    from app.llm.gemini import GeminiLLM

    assert Settings(_env_file=None).gemini_model == "gemini-3.5-flash"
    llm = GeminiLLM(Settings(_env_file=None), client=object(), model="gemini-3.5-flash")  # type: ignore[arg-type]
    assert llm._thinking_disabled() is False  # noqa: SLF001 (3.x cannot turn thinking off)


# --- tasks: in_progress ---------------------------------------------------------------------------
def test_task_in_progress_flows_through_counts(client, ws, db_session):
    acc = client.post(f"{ws}/accounts", json={"name": "Acme"}).json()
    today = date.today().isoformat()
    overdue = (date.today() - timedelta(days=3)).isoformat()
    t1 = client.post(
        f"{ws}/tasks", json={"title": "A", "account_id": acc["id"], "due_on": overdue}
    ).json()
    t2 = client.post(
        f"{ws}/tasks", json={"title": "B", "account_id": acc["id"], "due_on": today}
    ).json()
    base = client.get(f"{ws}/home").json()["kpis"]
    r = client.patch(f"{ws}/tasks/{t1['id']}", json={"status": "in_progress"})
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    assert client.patch(f"{ws}/tasks/{t2['id']}", json={"status": "in_progress"}).status_code == 200
    kpis = client.get(f"{ws}/home").json()["kpis"]
    assert (kpis["tasks_overdue"], kpis["tasks_due_week"]) == (
        base["tasks_overdue"],
        base["tasks_due_week"],
    )
    assert kpis["tasks_overdue"] >= 1
    assert {t["title"] for t in client.get(f"{ws}/home").json()["tasks"]} >= {"A", "B"}
    page = client.get(f"{ws}/tasks", params={"status": "in_progress"}).json()
    assert page["total"] == 2
    assert client.get(f"{ws}/tasks", params={"due": "overdue"}).json()["total"] == 1
    # in progress sorts before open
    client.post(f"{ws}/tasks", json={"title": "C", "account_id": acc["id"]})
    titles = [t["title"] for t in client.get(f"{ws}/tasks").json()["items"]]
    assert titles.index("C") > titles.index("A")
    # every status is settable, including back to suggested
    for status in ("suggested", "open", "in_progress", "done", "dismissed"):
        assert (
            client.patch(f"{ws}/tasks/{t1['id']}", json={"status": status}).json()["status"]
            == status
        )
    assert client.patch(f"{ws}/tasks/{t1['id']}", json={"status": "weird"}).status_code == 422
    row = db_session.get(Task, t1["id"])
    assert row.status == "dismissed"


def test_global_only_limit(client, ws):
    r = client.put(f"{ws}/admin/limits/mailbox_suggest_threshold", json={"value": 10})
    assert r.status_code == 400 and "global only" in r.text
    items = {i["key"]: i for i in client.get(f"{ws}/admin/limits").json()}
    assert items["mailbox_suggest_threshold"]["workspace_editable"] is False
    assert items["flow_max_rows"]["workspace_editable"] is True


def test_workspace_admin_does_not_see_superadmin_name(client, ws):
    key = "flow_max_rows"
    assert client.put(f"/api/admin/limits/{key}", json={"value": 5000}).status_code == 200
    rows = {i["key"]: i for i in client.get(f"{ws}/admin/limits").json()}
    assert rows[key]["updated_by"] is None
    glob = {i["key"]: i for i in client.get("/api/admin/limits").json()}
    assert glob[key]["updated_by"]


def test_set_override_survives_a_concurrent_first_write(db_session):
    from sqlalchemy import insert, select

    from app.db.models import SettingOverride
    from app.services import limits

    real = db_session.scalar
    calls = {"n": 0}

    def racy(stmt, *a, **k):
        calls["n"] += 1
        out = real(stmt, *a, **k)
        if calls["n"] <= 2:  # both lookups see nothing, then a rival inserts
            if calls["n"] == 2:
                db_session.execute(
                    insert(SettingOverride).values(key="flow_max_rows", value=2000)
                )
            return None
        return out

    db_session.scalar = racy
    try:
        limits.set_override(db_session, "flow_max_rows", None, 3000, None)
    finally:
        db_session.scalar = real
    db_session.commit()
    row = db_session.scalar(
        select(SettingOverride).where(SettingOverride.key == "flow_max_rows")
    )
    assert row.value == 3000


def test_models_failure_is_cached(client, ws, monkeypatch):
    llm_settings.clear_model_cache()
    n = []

    def boom(provider, key, settings):
        n.append(1)
        raise RuntimeError("down")

    monkeypatch.setattr(llm_settings, "fetch_provider_models", boom)
    client.put(f"{ws}/ai", json={"provider": "gemini", "model": "gemini-3.5-flash", "api_key": KEY})
    for _ in range(3):
        assert client.get(f"{ws}/ai/models").json()["source"] == "fallback"
    assert n == [1]  # the failure is remembered for a minute
    llm_settings.clear_model_cache()
