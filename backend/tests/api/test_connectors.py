"""TamTam connector routes: connect, callback, status, check, disconnect (respx for TamTam)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

import pytest

from app.api.deps import get_app_settings
from app.config import Settings
from app.connectors import store, tamtam
from tests.api.conftest import TEST_SECRET_KEY
from tests.connectors import conftest as shared
from tests.connectors.conftest import seed_credential
from tests.connectors.stubs import ACCESS_1, ACCESS_2, CODE, ISSUER, MCP_URL, SECRETS
from tests.enrichment.helpers import FakeSession, tool

# Fixtures shared with tests/connectors (re-exposed so pytest collects them here).
stub, ws = shared.stub, shared.ws

BASE = "/api/w/acme-real/connectors/tamtam"
CALLBACK = "/api/connectors/tamtam/callback"


def connect(client):
    response = client.post(f"{BASE}/connect")
    assert response.status_code == 200, response.text
    return response, parse_qs(urlsplit(response.json()["authorize_url"]).query)["state"][0]


def callback(client, **params):
    return client.get(CALLBACK, params=params, follow_redirects=False)


def full_connect(client):
    _, state = connect(client)
    response = callback(client, code=CODE, state=state)
    assert response.headers["location"] == "/w/acme-real/settings?tamtam=connected"
    return response


def test_status_when_not_connected(client, ws):
    body = client.get(BASE).json()
    assert body["status"] == "not_connected" and body["enrichment_mode"] == "off"
    assert body["secret_key_configured"] is True and body["resource"] == MCP_URL
    assert body["tools"] is None and body["pricing"] == {
        "email": 1.0,
        "mobile": 10.0,
        "ceiling": 10.0,
        "assumed": True,
    }


def test_unknown_workspace_is_404(client, stub):
    assert client.get("/api/w/nope/connectors/tamtam").status_code == 404
    assert client.post("/api/w/nope/connectors/tamtam/connect").status_code == 404
    assert client.post("/api/w/nope/connectors/tamtam/check").status_code == 404
    assert client.delete("/api/w/nope/connectors/tamtam").status_code == 404


def test_connect_sets_the_binding_cookie_and_returns_the_authorize_url(client, ws, stub):
    response, state = connect(client)
    url = response.json()["authorize_url"]
    assert set(response.json()) == {"authorize_url"}
    assert url.startswith(f"{ISSUER}/authorize?") and state
    cookie = response.headers["set-cookie"].lower()
    assert "df_oauth=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "path=/api/connectors" in cookie and "max-age=600" in cookie
    verifier_sent = [v for v in SECRETS if v in response.text]
    assert verifier_sent == []


def test_connect_without_a_secret_key_is_409_and_sends_nothing(app, client, ws, stub):
    bare = Settings(_env_file=None, environment="test")
    app.dependency_overrides[get_app_settings] = lambda: bare
    assert client.get(BASE).json()["secret_key_configured"] is False
    response = client.post(f"{BASE}/connect")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "connector_not_configured"
    assert "dataforce secrets init" in response.json()["error"]["message"]
    assert stub.traffic == 0


def test_connect_with_a_tampered_server_is_a_connector_error(client, ws, stub):
    stub.as_meta["token_endpoint"] = "https://evil.example/token"
    response = client.post(f"{BASE}/connect")
    assert response.status_code == 502 and response.json()["error"]["code"] == "connector_error"
    assert "evil.example" not in response.text


def test_full_flow_connect_callback_status_check_disconnect(
    client,
    ws,
    stub,
    db_session,
    monkeypatch,
    caplog,
):
    caplog.set_level(logging.DEBUG)
    bodies: list[str] = []
    response = full_connect(client)
    assert response.status_code == 303
    assert "df_oauth" in response.headers["set-cookie"]  # cleared
    assert "max-age=0" in response.headers["set-cookie"].lower()

    status = client.get(BASE)
    bodies.append(status.text)
    body = status.json()
    assert body["status"] == "connected" and body["enrichment_mode"] == "tamtam"
    assert body["issuer"] == ISSUER and body["token_expires_at"] and body["connected_at"]
    assert body["tools"] is None and body["last_error"] is None

    seen: list[str] = []
    session = FakeSession(
        [tool("enrich_contact", "Find a contact\x1b[0m"), tool("delete_everything", "danger")]
    )

    @asynccontextmanager
    async def opener(url, token):
        assert url == MCP_URL
        seen.append(token)
        yield session

    monkeypatch.setattr(tamtam, "open_http_session", opener)
    checked = client.post(f"{BASE}/check")
    bodies.append(checked.text)
    assert checked.status_code == 200
    tools = {t["name"]: t for t in checked.json()["tools"]}
    assert tools["enrich_contact"]["allowed"] is True
    assert tools["enrich_contact"]["description"] == "Find a contact"
    assert tools["delete_everything"]["allowed"] is False
    assert checked.json()["checked_at"] and seen == [ACCESS_1] and session.calls == []
    assert client.get(BASE).json()["tools"] == checked.json()["tools"]

    assert client.delete(BASE).status_code == 204
    after = client.get(BASE).json()
    assert after["status"] == "not_connected" and after["tools"] is None
    db_session.expire_all()
    assert store.get_credential(db_session, ws.id) is None

    for text in bodies:
        assert not [s for s in (*SECRETS, TEST_SECRET_KEY) if s in text]
    # (the test client's own httpx2 request lines are the "browser", not the app)
    logged = "\n".join(r.getMessage() for r in caplog.records if r.name != "httpx2")
    assert not [s for s in (*SECRETS, TEST_SECRET_KEY) if s in logged]


def test_callback_without_the_cookie_is_refused(client, ws, stub):
    _, state = connect(client)
    client.cookies.clear()
    response = callback(client, code=CODE, state=state)
    assert response.status_code == 303
    assert response.headers["location"] == "/w/acme-real/settings?tamtam=error&reason=invalid_state"
    assert stub.token_calls == []


def test_callback_with_a_wrong_cookie_is_refused(client, ws, stub):
    _, state = connect(client)
    client.cookies.clear()
    client.cookies.set("df_oauth", "forged", path="/api/connectors")
    response = callback(client, code=CODE, state=state)
    assert response.headers["location"].endswith("reason=invalid_state")
    assert stub.token_calls == []


def test_callback_state_is_single_use(client, ws, stub):
    _, state = connect(client)
    assert callback(client, code=CODE, state=state).headers["location"].endswith("connected")
    again = callback(client, code=CODE, state=state)
    assert again.headers["location"] == "/?tamtam=error&reason=invalid_state"
    assert len(stub.token_calls) == 1


def test_callback_with_an_expired_state(client, ws, stub, db_session):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.db.models import OAuthPending

    _, state = connect(client)
    db_session.scalars(select(OAuthPending)).one().expires_at = datetime.now(UTC) - timedelta(
        seconds=1
    )
    db_session.flush()
    response = callback(client, code=CODE, state=state)
    assert response.headers["location"] == "/w/acme-real/settings?tamtam=error&reason=expired"


def test_callback_with_a_mismatched_iss(client, ws, stub):
    _, state = connect(client)
    response = callback(client, code=CODE, state=state, iss="https://evil.example")
    assert response.headers["location"].endswith("reason=invalid_state")
    assert stub.token_calls == []


def test_callback_access_denied(client, ws, stub):
    _, state = connect(client)
    response = callback(client, error="access_denied", state=state)
    assert response.headers["location"] == "/w/acme-real/settings?tamtam=error&reason=denied"
    assert client.get(BASE).json()["status"] == "not_connected"


def test_callback_exchange_failure(client, ws, stub):
    stub.code_reply = (400, {"error": "invalid_grant"})
    _, state = connect(client)
    response = callback(client, code=CODE, state=state)
    assert response.headers["location"].endswith("reason=exchange_failed")
    assert client.get(BASE).json()["status"] == "not_connected"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"state": "<script>alert(1)</script>"},
        {"state": "x" * 5000, "code": "y" * 5000, "error": "e" * 5000, "iss": "i" * 5000},
        {"error": '"><img src=x onerror=alert(1)>', "state": "nope"},
    ],
)
def test_callback_always_answers_303_to_a_fixed_path_and_reflects_nothing(client, stub, params):
    response = callback(client, **params)
    assert response.status_code == 303
    assert response.headers["location"] == "/?tamtam=error&reason=invalid_state"
    assert response.content == b""
    for value in params.values():
        assert value not in response.headers["location"] and value not in response.text


def test_reason_is_always_one_of_the_fixed_codes(client, ws, stub):
    _, state = connect(client)
    response = callback(client, error="weird_error<>", state=state)
    reason = parse_qs(urlsplit(response.headers["location"]).query)["reason"][0]
    assert reason in {"denied", "expired", "invalid_state", "exchange_failed", "server_error"}


def test_check_when_not_connected_is_409(client, ws, stub):
    response = client.post(f"{BASE}/check")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "connector_not_configured"


def test_check_with_an_expired_sign_in_reports_expired(client, ws, stub, db_session, api_settings):
    from datetime import UTC, datetime, timedelta

    seed_credential(
        db_session, ws, api_settings, token_expires_at=datetime.now(UTC) - timedelta(seconds=5)
    )
    stub.refresh_reply = (400, {"error": "invalid_grant"})
    response = client.post(f"{BASE}/check")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "expired" and "reconnect" in body["last_error"]
    assert body["enrichment_mode"] == "off"
    assert not [s for s in SECRETS if s in response.text]


def test_check_refreshes_a_near_expiry_token_then_uses_it(
    client,
    ws,
    stub,
    db_session,
    api_settings,
    monkeypatch,
):
    from datetime import UTC, datetime, timedelta

    seed_credential(
        db_session, ws, api_settings, token_expires_at=datetime.now(UTC) + timedelta(seconds=20)
    )
    seen: list[str] = []

    @asynccontextmanager
    async def opener(url, token):
        seen.append(token)
        yield FakeSession([])

    monkeypatch.setattr(tamtam, "open_http_session", opener)
    assert client.post(f"{BASE}/check").status_code == 200
    assert seen == [ACCESS_2] and stub.token_calls[0]["grant_type"] == "refresh_token"


def test_check_failure_is_a_502_without_the_token(
    client,
    ws,
    stub,
    db_session,
    api_settings,
    monkeypatch,
):
    seed_credential(db_session, ws, api_settings)

    @asynccontextmanager
    async def opener(url, token):
        raise RuntimeError(f"cannot reach {token}")
        yield

    monkeypatch.setattr(tamtam, "open_http_session", opener)
    response = client.post(f"{BASE}/check")
    assert response.status_code == 502 and ACCESS_1 not in response.text
    assert client.get(BASE).json()["last_error"]


def test_disconnect_when_not_connected_is_204(client, ws, stub):
    assert client.delete(BASE).status_code == 204


def test_a_connection_belongs_to_its_workspace(client, ws, stub, db_session, api_settings):
    from app.services import workspaces

    other = workspaces.create_workspace(db_session, "other-ws", "Other")
    db_session.commit()
    seed_credential(db_session, ws, api_settings)
    assert client.get("/api/w/other-ws/connectors/tamtam").json()["status"] == "not_connected"
    assert client.delete("/api/w/other-ws/connectors/tamtam").status_code == 204
    assert client.get(BASE).json()["status"] == "connected"
    assert other.id != ws.id


def test_demo_workspace_reports_fake_mode(client, db_session, stub):
    from app.services import workspaces

    workspaces.create_workspace(db_session, "demo-x", "Demo", is_demo=True)
    db_session.commit()
    assert client.get("/api/w/demo-x/connectors/tamtam").json()["enrichment_mode"] == "fake"


@pytest.mark.parametrize("host", ["localhost:8800", "127.0.0.1:8800", "127.0.0.1:5173"])
def test_redirect_uri_and_cookie_share_the_browsers_host_and_round_trip(client, ws, stub, host):
    origin = {"Host": host, "Origin": f"http://{host}"}
    response = client.post(f"{BASE}/connect", headers=origin)
    assert response.status_code == 200, response.text
    query = parse_qs(urlsplit(response.json()["authorize_url"]).query)
    assert query["redirect_uri"] == [f"http://{host}/api/connectors/tamtam/callback"]
    assert stub.register_calls[-1]["redirect_uris"] == [query["redirect_uri"][0]]
    result = callback(client, code=CODE, state=query["state"][0])
    assert result.headers["location"] == "/w/acme-real/settings?tamtam=connected"
    assert stub.token_calls[-1]["redirect_uri"] == query["redirect_uri"][0]


def test_a_stored_client_is_re_registered_when_the_redirect_uri_changes(client, ws, stub):
    for host in ("127.0.0.1:8800", "127.0.0.1:8800", "localhost:8800"):
        response = client.post(
            f"{BASE}/connect", headers={"Host": host, "Origin": f"http://{host}"}
        )
        state = parse_qs(urlsplit(response.json()["authorize_url"]).query)["state"][0]
        assert callback(client, code=CODE, state=state).status_code == 303
    assert len(stub.register_calls) == 2  # reused on the repeat, re-registered for localhost
