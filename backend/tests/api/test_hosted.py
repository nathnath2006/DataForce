"""Hosted mode through the real app (docs/HOSTED-MODE-CONTRACT.md section 7)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_app_settings, get_session_factory
from app.config import Settings

pytestmark = pytest.mark.integration

ORIGIN = "https://dataforce-abc123-ew.a.run.app"


@pytest.fixture
def hosted_settings(api_settings) -> Settings:
    return api_settings.model_copy(
        update={"public_origin": ORIGIN, "allowed_hosts": ["df.custom.example"]}
    )


@pytest.fixture
def hosted(app, hosted_settings):
    """The app rebuilt in hosted mode, talking to the same test database."""
    from app.api.main import create_app

    hosted_app = create_app(hosted_settings)
    hosted_app.dependency_overrides = {
        **app.dependency_overrides,
        get_app_settings: lambda: hosted_settings,
    }
    host = "dataforce-abc123-ew.a.run.app"
    headers = {"Origin": ORIGIN, "X-DataForce": "1"}
    with TestClient(hosted_app, base_url=ORIGIN, headers=headers) as c:
        c.host = host  # type: ignore[attr-defined]
        yield c


def test_hosted_host_allow_list(hosted):
    assert hosted.get("/api/health").status_code == 200
    ok = hosted.get("/api/health", headers={"host": "df.custom.example"})
    assert ok.status_code == 200
    for host in ("127.0.0.1:8800", "localhost:8800", "evil.example"):
        assert hosted.get("/api/health", headers={"host": host}).status_code == 400


def test_hosted_origin_is_public_origin_only(hosted):
    body = {"email": "a@x.co", "password": "x"}
    for origin in ("http://127.0.0.1:8800", "https://evil.example"):
        r = hosted.post("/api/auth/login", json=body, headers={"Origin": origin})
        assert r.status_code == 403
    assert hosted.post("/api/auth/login", json=body).status_code == 401  # reached the route


def test_hsts_only_when_hosted(hosted, anon_client):
    assert "includeSubDomains" in hosted.get("/api/health").headers["strict-transport-security"]
    assert "strict-transport-security" not in anon_client.get("/api/health").headers


def test_hosted_session_cookie_secure_and_no_demo_chips(hosted):
    status = hosted.get("/api/auth/status").json()
    assert status["demo_logins"] == []
    r = hosted.post(
        "/api/auth/setup",
        json={"email": "h@x.co", "display_name": "H", "password": "S3cret-Passw0rd!"},
    )
    assert r.status_code == 201
    assert "secure" in r.headers["set-cookie"].lower()


def test_hosted_empty_password_refused(hosted, db_session):
    from app.services import workspaces

    workspaces.create_workspace(db_session, "demo-ws", "Demo", is_demo=True)
    db_session.flush()
    hosted.post(
        "/api/auth/setup",
        json={"email": "h@x.co", "display_name": "H", "password": "S3cret-Passw0rd!"},
    )
    r = hosted.post(
        "/api/w/demo-ws/members", json={"email": "d@x.co", "display_name": "D", "password": ""}
    )
    assert r.status_code == 422


def test_hosted_oauth_cookies_secure(hosted, monkeypatch):
    from app.connectors import tamtam
    from app.services import mailbox as svc

    async def fake(*a, **k):
        return "https://auth.example/authorize", "browser-secret"

    monkeypatch.setattr(tamtam, "start_connect", fake)
    monkeypatch.setattr(svc, "start_connect", fake)
    hosted.post(
        "/api/auth/setup",
        json={"email": "h@x.co", "display_name": "H", "password": "S3cret-Passw0rd!"},
    )
    from app.db.models import Workspace  # noqa: F401

    hosted.post("/api/workspaces", json={"slug": "hw", "name": "HW"})
    for path in ("/api/w/hw/connectors/tamtam/connect", "/api/w/hw/mailbox/gmail/connect"):
        r = hosted.post(path)
        assert r.status_code == 200, path
        assert "secure" in r.headers["set-cookie"].lower(), path


def test_reset_link_uses_public_origin(hosted, caplog):
    hosted.post(
        "/api/auth/setup",
        json={"email": "h@x.co", "display_name": "H", "password": "S3cret-Passw0rd!"},
    )
    with caplog.at_level("WARNING"):
        assert hosted.post("/api/auth/forgot", json={"email": "h@x.co"}).status_code == 202
    assert f"{ORIGIN}/reset?token=" in caplog.text


# --- health ----------------------------------------------------------------------------------
def test_health_ok(anon_client):
    r = anon_client.get("/api/health")
    assert r.status_code == 200 and r.json()["database"] == "ok" and r.json()["ok"] is True


def test_health_503_without_leaking(app, anon_client):
    class Broken:
        def __call__(self):
            raise RuntimeError("connection to db.secret-host.example password=hunter2 failed")

    app.dependency_overrides[get_session_factory] = lambda: Broken()
    r = anon_client.get("/api/health")
    assert r.status_code == 503
    assert r.json()["ok"] is False and r.json()["database"] == "unavailable"
    assert "secret-host" not in r.text and "hunter2" not in r.text
