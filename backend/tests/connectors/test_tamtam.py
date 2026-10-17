"""Connect, callback, refresh, check and disconnect (service level, respx for TamTam)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors import oauth, store, tamtam
from app.connectors.crypto import seal, unseal
from app.db.models import ConnectorCredential, OAuthPending
from app.enrichment.errors import EnrichmentConfigError, EnrichmentError
from tests.connectors.stubs import (
    ACCESS_1,
    ACCESS_2,
    CLIENT_ID,
    CODE,
    ISSUER,
    MCP_URL,
    REFRESH_1,
    REFRESH_2,
    SECRETS,
)
from tests.enrichment.helpers import FakeSession, tool


async def start(db, settings, ws):
    url, browser = await tamtam.start_connect(db, settings, ws.id)
    state = parse_qs(urlsplit(url).query)["state"][0]
    return url, browser, state


async def finish(db, settings, state, browser, **kw):
    args = {"code": CODE, "iss": None, "error": None, **kw}
    return await tamtam.finish_callback(db, settings, state=state, browser_cookie=browser, **args)


async def connect(db, settings, ws):
    _, browser, state = await start(db, settings, ws)
    result = await finish(db, settings, state, browser)
    assert result.reason is None, result
    return result


def credential(db: Session, ws) -> ConnectorCredential:
    db.expire_all()
    cred = store.get_credential(db, ws.id)
    assert cred is not None
    return cred


def pending_count(db: Session) -> int:
    return len(db.scalars(select(OAuthPending)).all())


# --- connect --------------------------------------------------------------------------------


async def test_connect_registers_and_builds_the_authorize_url(db_session, settings, ws, stub):
    url, browser, state = await start(db_session, settings, ws)
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert url.startswith(f"{ISSUER}/authorize?")
    assert q["client_id"] == CLIENT_ID and q["resource"] == MCP_URL
    assert q["code_challenge_method"] == "S256" and "scope" not in q
    assert q["redirect_uri"] == "http://127.0.0.1:8800/api/connectors/tamtam/callback"
    assert len(stub.register_calls) == 1
    pending = db_session.scalars(select(OAuthPending)).one()
    # only hashes of the state and the cookie, and the sealed verifier, are stored
    assert state not in (pending.state_hash, pending.browser_hash)
    assert pending.state_hash == store.sha256_hex(state)
    assert pending.browser_hash == store.sha256_hex(browser)
    assert len(unseal(pending.code_verifier_enc, settings)) >= 43
    assert (pending.expires_at - datetime.now(UTC)) <= timedelta(minutes=10)


async def test_connect_without_a_secret_key_is_a_config_error_and_sends_nothing(
    db_session, ws, stub
):
    from app.config import Settings

    bare = Settings(_env_file=None, environment="test")
    with pytest.raises(EnrichmentConfigError, match="dataforce secrets init"):
        await tamtam.start_connect(db_session, bare, ws.id)
    assert stub.traffic == 0


async def test_a_new_connect_replaces_the_flow_in_flight(db_session, settings, ws, stub):
    await start(db_session, settings, ws)
    await start(db_session, settings, ws)
    assert pending_count(db_session) == 1


async def test_reconnect_reuses_the_client_id_for_the_same_redirect_uri(
    db_session, settings, ws, stub
):
    await connect(db_session, settings, ws)
    await start(db_session, settings, ws)
    assert len(stub.register_calls) == 1  # registered once


async def test_reconnect_registers_again_when_the_redirect_uri_changed(
    db_session, settings, ws, stub
):
    from app.config import Settings

    await connect(db_session, settings, ws)
    moved = Settings(
        _env_file=None,
        environment="test",
        dataforce_secret_key=settings.dataforce_secret_key,
        ui_port=9000,
    )
    await start(db_session, moved, ws)
    assert len(stub.register_calls) == 2


async def test_connect_refuses_a_tampered_discovery(db_session, settings, ws, stub):
    stub.as_meta["authorization_endpoint"] = "https://evil.example/authorize"
    with pytest.raises(oauth.OAuthError):
        await start(db_session, settings, ws)
    assert pending_count(db_session) == 0


# --- callback -------------------------------------------------------------------------------


async def test_happy_path_stores_sealed_tokens(db_session, settings, ws, stub):
    result = await connect(db_session, settings, ws)
    assert result.slug == ws.slug
    cred = credential(db_session, ws)
    assert cred.status == "connected" and cred.issuer == ISSUER and cred.resource == MCP_URL
    assert cred.client_id == CLIENT_ID and cred.token_expires_at is not None
    for sealed in (cred.access_token_enc, cred.refresh_token_enc):
        assert not any(s in sealed for s in SECRETS)
    assert unseal(cred.access_token_enc, settings) == ACCESS_1
    assert unseal(cred.refresh_token_enc, settings) == REFRESH_1
    assert pending_count(db_session) == 0  # single use
    assert stub.token_calls[0]["code_verifier"]


async def test_state_is_single_use(db_session, settings, ws, stub):
    _, browser, state = await start(db_session, settings, ws)
    assert (await finish(db_session, settings, state, browser)).reason is None
    again = await finish(db_session, settings, state, browser)
    assert again.reason == tamtam.INVALID_STATE and again.slug is None
    assert len(stub.token_calls) == 1


async def test_unknown_or_missing_state(db_session, settings, ws, stub):
    for state in (None, "", "x" * 1000, "never-issued"):
        result = await finish(db_session, settings, state, "cookie")
        assert result.reason == tamtam.INVALID_STATE and result.slug is None
    assert stub.token_calls == []


async def test_expired_state(db_session, settings, ws, stub):
    _, browser, state = await start(db_session, settings, ws)
    pending = db_session.scalars(select(OAuthPending)).one()
    pending.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    result = await finish(db_session, settings, state, browser)
    assert result.reason == tamtam.EXPIRED and result.slug == ws.slug
    assert stub.token_calls == [] and pending_count(db_session) == 0


@pytest.mark.parametrize("cookie", [None, "", "wrong-cookie"])
async def test_missing_or_wrong_cookie(db_session, settings, ws, stub, cookie):
    _, browser, state = await start(db_session, settings, ws)
    result = await finish(db_session, settings, state, cookie)
    assert result.reason == tamtam.INVALID_STATE
    assert stub.token_calls == []
    assert pending_count(db_session) == 0  # a wrong attempt spends the flow
    assert store.get_credential(db_session, ws.id) is None


async def test_mismatched_iss(db_session, settings, ws, stub):
    _, browser, state = await start(db_session, settings, ws)
    result = await finish(db_session, settings, state, browser, iss="https://evil.example")
    assert result.reason == tamtam.INVALID_STATE
    assert stub.token_calls == []


async def test_matching_iss_is_accepted(db_session, settings, ws, stub):
    _, browser, state = await start(db_session, settings, ws)
    assert (await finish(db_session, settings, state, browser, iss=ISSUER)).reason is None


async def test_iss_is_required_when_the_server_declares_support(db_session, settings, ws, stub):
    stub.as_meta["authorization_response_iss_parameter_supported"] = True
    _, browser, state = await start(db_session, settings, ws)
    assert (await finish(db_session, settings, state, browser)).reason == tamtam.INVALID_STATE


async def test_access_denied(db_session, settings, ws, stub):
    _, browser, state = await start(db_session, settings, ws)
    result = await finish(db_session, settings, state, browser, error="access_denied", code=None)
    assert result.reason == tamtam.DENIED and result.slug == ws.slug
    assert stub.token_calls == []


async def test_other_authorization_errors_are_server_errors(db_session, settings, ws, stub):
    _, browser, state = await start(db_session, settings, ws)
    result = await finish(db_session, settings, state, browser, error="<script>x</script>")
    assert result.reason == tamtam.SERVER_ERROR


async def test_a_denial_needs_a_valid_state_and_cookie_first(db_session, settings, ws, stub):
    _, browser, state = await start(db_session, settings, ws)
    result = await finish(db_session, settings, state, "bad", error="access_denied")
    assert result.reason == tamtam.INVALID_STATE


@pytest.mark.parametrize("code", [None, "", "c" * 5000])
async def test_missing_or_oversized_code(db_session, settings, ws, stub, code):
    _, browser, state = await start(db_session, settings, ws)
    assert (await finish(db_session, settings, state, browser, code=code)).reason == (
        tamtam.EXCHANGE_FAILED
    )
    assert stub.token_calls == []


async def test_exchange_failures_leave_no_credential(db_session, settings, ws, stub):
    stub.code_reply = (400, {"error": "invalid_grant"})
    _, browser, state = await start(db_session, settings, ws)
    assert (await finish(db_session, settings, state, browser)).reason == tamtam.EXCHANGE_FAILED
    assert store.get_credential(db_session, ws.id) is None

    stub.code_reply = (200, {"access_token": "a", "token_type": "mac"})
    _, browser, state = await start(db_session, settings, ws)
    assert (await finish(db_session, settings, state, browser)).reason == tamtam.EXCHANGE_FAILED
    assert store.get_credential(db_session, ws.id) is None


async def test_issuer_changed_between_connect_and_callback(db_session, settings, ws, stub):
    _, browser, state = await start(db_session, settings, ws)
    pending = db_session.scalars(select(OAuthPending)).one()
    pending.issuer = "https://api.tamtam.ai/other"
    db_session.commit()
    assert (await finish(db_session, settings, state, browser)).reason == tamtam.EXCHANGE_FAILED


async def test_oversized_token_answer_fails_the_exchange(db_session, settings, ws, stub):
    _, browser, state = await start(db_session, settings, ws)
    stub.mock.post(f"{ISSUER}/token").mock(
        return_value=httpx.Response(
            200,
            content=b'{"a":"' + b"a" * 70000 + b'"}',
            headers={"content-type": "application/json"},
        )
    )
    assert (await finish(db_session, settings, state, browser)).reason == tamtam.EXCHANGE_FAILED


# --- using the token: refresh and rotation ---------------------------------------------------


def age_token(db, ws, seconds_left: int):
    cred = credential(db, ws)
    cred.token_expires_at = datetime.now(UTC) + timedelta(seconds=seconds_left)
    db.commit()


async def test_a_fresh_token_is_used_without_any_traffic(db_session, settings, ws, stub):
    await connect(db_session, settings, ws)
    before = stub.traffic
    assert await tamtam.access_token(db_session, settings, ws.id) == ACCESS_1
    assert stub.traffic == before


async def test_refresh_when_less_than_sixty_seconds_are_left_and_rotation(
    db_session, settings, ws, stub
):
    await connect(db_session, settings, ws)
    age_token(db_session, ws, 30)
    assert await tamtam.access_token(db_session, settings, ws.id) == ACCESS_2
    cred = credential(db_session, ws)
    assert unseal(cred.access_token_enc, settings) == ACCESS_2
    assert unseal(cred.refresh_token_enc, settings) == REFRESH_2  # rotated token replaced it
    assert cred.token_expires_at > datetime.now(UTC) + timedelta(minutes=30)
    assert stub.token_calls[-1]["refresh_token"] == REFRESH_1
    assert cred.status == "connected"
    # and the new token is now fresh: no second refresh
    n = len(stub.token_calls)
    await tamtam.access_token(db_session, settings, ws.id)
    assert len(stub.token_calls) == n


async def test_invalid_grant_marks_the_credential_expired(db_session, settings, ws, stub):
    await connect(db_session, settings, ws)
    age_token(db_session, ws, -5)
    stub.refresh_reply = (400, {"error": "invalid_grant"})
    with pytest.raises(tamtam.ConnectorNotUsable):
        await tamtam.access_token(db_session, settings, ws.id)
    cred = credential(db_session, ws)
    assert cred.status == "expired" and "reconnect" in cred.last_error
    with pytest.raises(tamtam.ConnectorNotUsable, match="expired"):
        await tamtam.access_token(db_session, settings, ws.id)  # no more traffic attempts
    assert len(stub.token_calls) == 2


async def test_a_transient_refresh_failure_keeps_the_credential_connected(
    db_session, settings, ws, stub
):
    await connect(db_session, settings, ws)
    age_token(db_session, ws, -5)
    stub.refresh_reply = (503, {"error": "temporarily_unavailable"})
    with pytest.raises(EnrichmentError):
        await tamtam.access_token(db_session, settings, ws.id)
    assert credential(db_session, ws).status == "connected"


async def test_expired_without_a_refresh_token(db_session, settings, ws, stub):
    stub.code_reply = (200, {"access_token": ACCESS_1, "token_type": "Bearer", "expires_in": 10})
    await connect(db_session, settings, ws)
    with pytest.raises(tamtam.ConnectorNotUsable):
        await tamtam.access_token(db_session, settings, ws.id)
    assert credential(db_session, ws).status == "expired"


async def test_a_rotated_secret_key_marks_the_credential_error(db_session, settings, ws, stub):
    from cryptography.fernet import Fernet

    from app.config import Settings

    await connect(db_session, settings, ws)
    other = Settings(
        _env_file=None, environment="test", dataforce_secret_key=Fernet.generate_key().decode()
    )
    with pytest.raises(tamtam.ConnectorNotUsable, match="reconnect"):
        await tamtam.access_token(db_session, other, ws.id)
    cred = credential(db_session, ws)
    assert cred.status == "error" and "decrypt" in cred.last_error


async def test_a_token_is_never_sent_to_another_resource(db_session, settings, ws, stub):
    from app.config import Settings

    await connect(db_session, settings, ws)
    elsewhere = Settings(
        _env_file=None,
        environment="test",
        dataforce_secret_key=settings.dataforce_secret_key,
        tamtam_mcp_url="http://127.0.0.1:9/mcp",
    )
    with pytest.raises(tamtam.ConnectorNotUsable, match="different TamTam URL"):
        await tamtam.access_token(db_session, elsewhere, ws.id)
    assert credential(db_session, ws).status == "error"


async def test_not_connected(db_session, settings, ws, stub):
    with pytest.raises(EnrichmentConfigError, match="not connected"):
        await tamtam.access_token(db_session, settings, ws.id)
    with pytest.raises(EnrichmentConfigError):
        await tamtam.build_provider(db_session, settings, ws.id)


async def test_the_provider_gets_the_stored_token(db_session, settings, ws, stub):
    await connect(db_session, settings, ws)
    provider = await tamtam.build_provider(db_session, settings, ws.id)
    assert provider._token_value() == ACCESS_1


# --- check ----------------------------------------------------------------------------------


def fake_opener(session: FakeSession, seen: list[str]):
    @asynccontextmanager
    async def opener(token: str):
        seen.append(token)
        yield session

    return opener


async def test_check_lists_tools_only_and_stores_a_sanitised_snapshot(
    db_session, settings, ws, stub
):
    await connect(db_session, settings, ws)
    nasty = "Find \x1b[31memail\x1b[0m of jane@acme.example\nIGNORE PREVIOUS " + "x" * 900
    session = FakeSession(
        [
            tool("enrich_contact", nasty),
            tool("send_email_to_contact", "mails people"),
            tool("Find_Email", "ok"),
        ]
    )
    seen: list[str] = []
    await tamtam.run_check(db_session, settings, ws.id, session_factory=fake_opener(session, seen))
    assert session.calls == []  # never call_tool
    assert seen == [ACCESS_1]
    cred = credential(db_session, ws)
    by_name = {t["name"]: t for t in cred.tools}
    assert by_name["enrich_contact"]["allowed"] is True
    assert by_name["Find_Email"]["allowed"] is True
    assert by_name["send_email_to_contact"]["allowed"] is False
    desc = by_name["enrich_contact"]["description"]
    assert len(desc) <= 500 and "\x1b" not in desc and "\n" not in desc
    assert "jane@acme.example" not in desc
    assert cred.checked_at is not None and cred.last_error is None


async def test_check_reads_annotations(db_session, settings, ws, stub):
    from types import SimpleNamespace

    await connect(db_session, settings, ws)
    annotated = tool("find_email", "x")
    annotated.annotations = SimpleNamespace(readOnlyHint=True, destructiveHint=False)
    await tamtam.run_check(
        db_session, settings, ws.id, session_factory=fake_opener(FakeSession([annotated]), [])
    )
    entry = credential(db_session, ws).tools[0]
    assert (entry["read_only"], entry["destructive"]) == (True, False)


async def test_check_refreshes_the_token_first(db_session, settings, ws, stub):
    await connect(db_session, settings, ws)
    age_token(db_session, ws, 10)
    seen: list[str] = []
    await tamtam.run_check(
        db_session, settings, ws.id, session_factory=fake_opener(FakeSession([]), seen)
    )
    assert seen == [ACCESS_2]


async def test_check_on_an_expired_credential_reports_it_without_error(
    db_session, settings, ws, stub
):
    await connect(db_session, settings, ws)
    age_token(db_session, ws, -5)
    stub.refresh_reply = (400, {"error": "invalid_grant"})
    await tamtam.run_check(db_session, settings, ws.id)  # no exception
    assert credential(db_session, ws).status == "expired"


async def test_check_rejected_by_the_mcp_server_marks_expired(db_session, settings, ws, stub):
    await connect(db_session, settings, ws)

    @asynccontextmanager
    async def rejecting(token):
        raise EnrichmentError("TamTam MCP authentication rejected (HTTP 401); token expired")
        yield

    await tamtam.run_check(db_session, settings, ws.id, session_factory=rejecting)
    assert credential(db_session, ws).status == "expired"


async def test_check_failure_is_recorded_and_raised_without_the_token(
    db_session, settings, ws, stub
):
    await connect(db_session, settings, ws)

    @asynccontextmanager
    async def broken(token):
        raise RuntimeError(f"boom {token}")
        yield

    with pytest.raises(EnrichmentError) as exc:
        await tamtam.run_check(db_session, settings, ws.id, session_factory=broken)
    assert ACCESS_1 not in str(exc.value)
    cred = credential(db_session, ws)
    assert cred.status == "connected" and ACCESS_1 not in cred.last_error


async def test_check_without_a_connection(db_session, settings, ws, stub):
    with pytest.raises(EnrichmentConfigError):
        await tamtam.run_check(db_session, settings, ws.id)


async def test_check_over_the_real_mcp_transport_sends_the_bearer(db_session, settings, ws, stub):
    """Loopback MCP server (no external network): list_tools only, with the stored token."""
    from app.config import Settings
    from tests.enrichment.test_mcp_loopback import mcp_url as _fixture  # noqa: F401

    pytest.importorskip("uvicorn")
    pytest.importorskip("mcp.server.mcpserver")
    import asyncio
    import socket

    import uvicorn
    from mcp.server import mcpserver

    from tests.enrichment.test_mcp_loopback import BearerGate

    server = mcpserver.MCPServer("fake-tamtam")
    called: list[str] = []

    @server.tool()
    def enrich_contact(full_name: str) -> str:
        """Find a contact (test double)."""
        called.append(full_name)
        return "{}"

    gate = BearerGate(server.streamable_http_app(), ACCESS_1)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(
        uvicorn.Config(gate, host="127.0.0.1", port=port, log_level="error", lifespan="on")
    )
    task = asyncio.create_task(srv.serve())
    for _ in range(200):
        if srv.started:
            break
        await asyncio.sleep(0.05)
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        local = Settings(
            _env_file=None,
            environment="test",
            dataforce_secret_key=settings.dataforce_secret_key,
            tamtam_mcp_url=url,
        )
        # a credential issued for that resource, with a fresh token
        store.save_credential(
            db_session,
            ws.id,
            status="connected",
            issuer=ISSUER,
            resource=url,
            client_id=CLIENT_ID,
            client_secret_enc=None,
            redirect_uri="http://127.0.0.1:8800/api/connectors/tamtam/callback",
            access_token_enc=seal(ACCESS_1, local),
            refresh_token_enc=seal(REFRESH_1, local),
            token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db_session.commit()
        await tamtam.run_check(db_session, local, ws.id)
        tools = credential(db_session, ws).tools
        assert [t["name"] for t in tools] == ["enrich_contact"] and tools[0]["allowed"]
        assert called == []
        assert set(gate.seen) == {f"Bearer {ACCESS_1}"}
    finally:
        srv.should_exit = True
        await task


# --- disconnect, status, secrets in logs ------------------------------------------------------


async def test_disconnect_deletes_credential_and_pending_rows(db_session, settings, ws, stub):
    await connect(db_session, settings, ws)
    await start(db_session, settings, ws)  # a flow in flight too
    await tamtam.disconnect(db_session, settings, ws.id)
    assert store.get_credential(db_session, ws.id) is None and pending_count(db_session) == 0
    assert stub.revoke_calls == []  # TamTam advertises no revocation endpoint


async def test_disconnect_revokes_when_the_server_advertises_an_endpoint(
    db_session, settings, ws, stub
):
    stub.as_meta["revocation_endpoint"] = f"{ISSUER}/revoke"
    await connect(db_session, settings, ws)
    await tamtam.disconnect(db_session, settings, ws.id)
    assert store.get_credential(db_session, ws.id) is None
    assert stub.revoke_calls == [{"token": REFRESH_1, "client_id": CLIENT_ID}]


async def test_disconnect_survives_a_failing_revocation(db_session, settings, ws, stub):
    stub.as_meta["revocation_endpoint"] = f"{ISSUER}/revoke"
    await connect(db_session, settings, ws)
    stub.mock.post(f"{ISSUER}/revoke").mock(side_effect=httpx.ConnectError("down"))
    await tamtam.disconnect(db_session, settings, ws.id)
    assert store.get_credential(db_session, ws.id) is None


async def test_disconnect_when_nothing_is_connected(db_session, settings, ws, stub):
    await tamtam.disconnect(db_session, settings, ws.id)
    assert stub.traffic == 0


def test_status_view_has_no_secret(db_session, settings, ws):
    view = tamtam.status_view(db_session, settings, ws)
    assert view.status == "not_connected" and view.enrichment_mode == "off"
    assert view.secret_key_configured and view.pricing.email == 1 and view.pricing.mobile == 10
    assert view.resource == MCP_URL


async def test_no_secret_reaches_the_logs(db_session, settings, ws, stub, caplog):
    caplog.set_level(logging.DEBUG)
    await connect(db_session, settings, ws)
    age_token(db_session, ws, 5)
    await tamtam.access_token(db_session, settings, ws.id)
    stub.refresh_reply = (400, {"error": "invalid_grant"})
    age_token(db_session, ws, 5)
    with pytest.raises(tamtam.ConnectorNotUsable):
        await tamtam.access_token(db_session, settings, ws.id)
    await tamtam.disconnect(db_session, settings, ws.id)
    text = caplog.text
    secret_key = settings.dataforce_secret_key.get_secret_value()
    for secret in (*SECRETS, secret_key):
        assert secret not in text


# --- SR7: races, issuer binding ---------------------------------------------------------------


async def test_a_refresh_does_not_overwrite_a_newer_reconnect(db_session, settings, ws, stub):
    await connect(db_session, settings, ws)
    age_token(db_session, ws, 30)

    def reconnect_mid_refresh():
        store.save_credential(
            db_session,
            ws.id,
            access_token_enc=seal("access-from-reconnect", settings),
            refresh_token_enc=seal("refresh-from-reconnect", settings),
            token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db_session.commit()

    stub.on_token = reconnect_mid_refresh
    token = await tamtam.access_token(db_session, settings, ws.id)
    assert token == "access-from-reconnect"
    cred = credential(db_session, ws)
    assert unseal(cred.access_token_enc, settings) == "access-from-reconnect"
    assert unseal(cred.refresh_token_enc, settings) == "refresh-from-reconnect"


async def test_a_refresh_does_not_revive_a_disconnected_credential(db_session, settings, ws, stub):
    await connect(db_session, settings, ws)
    age_token(db_session, ws, 30)

    def disconnect_mid_refresh():
        store.delete_credential(db_session, ws.id)
        db_session.commit()

    stub.on_token = disconnect_mid_refresh
    with pytest.raises(EnrichmentConfigError):
        await tamtam.access_token(db_session, settings, ws.id)
    assert store.get_credential(db_session, ws.id) is None


async def test_a_stored_client_is_not_reused_for_another_issuer(db_session, settings, ws, stub):
    await connect(db_session, settings, ws)
    assert len(stub.register_calls) == 1
    cred = credential(db_session, ws)
    cred.issuer = "https://other.example"
    db_session.commit()
    await start(db_session, settings, ws)
    assert len(stub.register_calls) == 2  # same redirect URI, different issuer: re-register
