from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import LlmCall, Run, Workspace

pytestmark = pytest.mark.integration


def _ws(client, slug):
    client.post("/api/workspaces", json={"slug": slug, "name": slug})
    return f"/api/w/{slug}/admin"


def _id(db, slug):
    return db.query(Workspace).filter_by(slug=slug).one().id


def test_overview_shape_and_allowlist(client):
    base = _ws(client, "adm")
    b = client.get(f"{base}/overview").json()
    assert b["database"]["quota_mb"] == 500 and b["database"]["tables"]
    assert {"size_bytes", "used_pct"} <= set(b["database"])
    assert set(b["schema_status"]) == {"current", "head", "up_to_date"}
    assert b["limits"] and all(set(x) == {"name", "value", "description"} for x in b["limits"])
    banned = ("key", "secret", "password", "url", "token", "dsn")
    for x in b["limits"]:
        assert not any(w in x["name"].lower().replace("tokens", "") for w in banned)
        assert isinstance(x["value"], int | float)
        assert "postgresql" not in str(x["value"]).lower()


def test_runs_filters_limit_stale(client, db_session):
    base = _ws(client, "adm-r")
    wid = _id(db_session, "adm-r")
    old = datetime.now(UTC) - timedelta(hours=2)
    db_session.add_all(
        [
            Run(
                workspace_id=wid,
                kind="agent_call",
                status="running",
                params={"tool": "x"},
                started_at=old,
            ),
            Run(workspace_id=wid, kind="stats_scan", status="running", params={}),
            Run(workspace_id=wid, kind="stats_scan", status="failed", params={}, error="boom"),
        ]
    )
    db_session.commit()
    allr = client.get(f"{base}/runs").json()["runs"]
    assert len(allr) == 3
    stale = [r for r in allr if r["stale"]]
    assert len(stale) == 1 and stale[0]["summary"] == "agent_call: x"
    assert len(client.get(f"{base}/runs?kind=stats_scan").json()["runs"]) == 2
    assert len(client.get(f"{base}/runs?status=failed").json()["runs"]) == 1
    assert len(client.get(f"{base}/runs?limit=1").json()["runs"]) == 1
    assert client.get(f"{base}/runs?limit=201").status_code == 422


def test_ai_usage_and_isolation(client, db_session):
    base = _ws(client, "adm-a")
    _ws(client, "adm-b")
    a, b = _id(db_session, "adm-a"), _id(db_session, "adm-b")
    row = dict(provider="p", model="m", purpose="title_classification", latency_ms=1)
    db_session.add_all(
        [
            LlmCall(workspace_id=a, success=True, input_tokens=10, output_tokens=5, **row),
            LlmCall(workspace_id=a, success=False, **row),
            LlmCall(workspace_id=b, success=True, **row),
            LlmCall(
                workspace_id=a,
                success=True,
                created_at=datetime.now(UTC) - timedelta(days=40),
                **row,
            ),
        ]
    )
    db_session.commit()
    body = client.get(f"{base}/ai-usage?days=30").json()
    assert "llm_call" in body["source"]
    assert len(body["rows"]) == 1
    r = body["rows"][0]
    assert (r["calls"], r["failures"], r["input_tokens"]) == (2, 1, 10)
    t = {x["purpose"]: x for x in body["today"]}
    assert t["title_classification"]["calls"] == 2 and t["title_classification"]["daily_cap"] > 0
    assert client.get(f"{base}/ai-usage?days=90").json()["rows"][0]["calls"] == 3
