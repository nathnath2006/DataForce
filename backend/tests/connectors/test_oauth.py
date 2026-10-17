"""Discovery, registration, PKCE, code exchange and refresh against TamTam's real metadata
(served by respx). Every refusal of docs/UI-CONTRACT.md section 4 is here."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.config import Settings
from app.connectors import oauth
from tests.connectors.stubs import (
    ACCESS_1,
    ACCESS_2,
    CLIENT_ID,
    CODE,
    ISSUER,
    MCP_URL,
    PRM_ROOT_URL,
    PRM_URL,
    REFRESH_1,
    REFRESH_2,
)

REDIRECT = "http://127.0.0.1:8800/api/connectors/tamtam/callback"


async def discover(settings):
    async with oauth.new_client() as client:
        return await oauth.discover(client, settings)


# --- discovery -----------------------------------------------------------------------------


async def test_discovery_with_tamtams_real_metadata(settings, stub):
    meta = await discover(settings)
    assert meta.issuer == ISSUER
    assert meta.authorization_endpoint == f"{ISSUER}/authorize"
    assert meta.token_endpoint == f"{ISSUER}/token"
    assert meta.registration_endpoint == f"{ISSUER}/register"
    assert meta.scope is None  # TamTam lists no scopes_supported: none is sent


async def test_root_prm_is_the_fallback_when_the_path_inserted_one_is_missing(settings, stub):
    stub.mock.get(PRM_URL).mock(return_value=httpx.Response(404))
    stub.mock.get(PRM_ROOT_URL).mock(return_value=httpx.Response(200, json=stub.prm))
    assert (await discover(settings)).issuer == ISSUER


async def test_no_protected_resource_metadata_at_all(settings, stub):
    stub.mock.get(PRM_URL).mock(return_value=httpx.Response(404))
    stub.mock.get(PRM_ROOT_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(oauth.OAuthError, match="no protected-resource"):
        await discover(settings)


async def test_prm_resource_must_equal_the_mcp_url(settings, stub):
    stub.prm["resource"] = "https://evil.example/mcp"
    with pytest.raises(oauth.OAuthError, match="different resource"):
        await discover(settings)


async def test_prm_resource_ignores_a_trailing_slash(settings, stub):
    stub.prm["resource"] = MCP_URL + "/"
    assert (await discover(settings)).issuer == ISSUER


async def test_issuer_outside_the_allow_list_is_refused(settings, stub):
    stub.prm["authorization_servers"] = ["https://evil.example"]
    with pytest.raises(oauth.OAuthError, match="not in the allowed list"):
        await discover(settings)
    assert not any("evil.example" in str(c.request.url) for c in stub.mock.calls)  # not fetched


async def test_as_metadata_issuer_must_match_exactly(settings, stub):
    stub.as_meta["issuer"] = "https://api.tamtam.ai/other"
    with pytest.raises(oauth.OAuthError, match="issuer does not match"):
        await discover(settings)


@pytest.mark.parametrize(
    "key", ["authorization_endpoint", "token_endpoint", "registration_endpoint"]
)
@pytest.mark.parametrize(
    "bad",
    [
        "https://evil.example/token",  # off origin
        "http://api.tamtam.ai/token",  # not https
        "https://api.tamtam.ai.evil.example/token",  # look-alike host
        "https://user:pw@api.tamtam.ai/token",  # credentials
        "https://api.tamtam.ai:8443/token",  # other port = other origin
        "/token",  # relative
    ],
)
async def test_every_endpoint_must_be_https_on_the_issuers_origin(settings, stub, key, bad):
    stub.as_meta[key] = bad
    with pytest.raises(oauth.OAuthError, match="issuer's origin|no valid"):
        await discover(settings)


async def test_revocation_endpoint_is_checked_too(settings, stub):
    stub.as_meta["revocation_endpoint"] = "https://evil.example/revoke"
    with pytest.raises(oauth.OAuthError):
        await discover(settings)


@pytest.mark.parametrize("methods", [["plain"], [], None])
async def test_s256_is_required(settings, stub, methods):
    if methods is None:
        del stub.as_meta["code_challenge_methods_supported"]
    else:
        stub.as_meta["code_challenge_methods_supported"] = methods
    with pytest.raises(oauth.OAuthError, match="S256"):
        await discover(settings)


async def test_a_server_without_the_code_grant_is_refused(settings, stub):
    stub.as_meta["response_types_supported"] = ["token"]
    with pytest.raises(oauth.OAuthError):
        await discover(settings)


async def test_scope_is_sent_only_if_the_metadata_lists_scopes(settings, stub):
    stub.as_meta["scopes_supported"] = ["mcp", "offline_access"]
    meta = await discover(settings)
    assert meta.scope == "mcp offline_access"
    url = oauth.build_authorize_url(
        meta, client_id="c", redirect_uri=REDIRECT, state="s", challenge="ch", resource=MCP_URL
    )
    assert parse_qs(urlsplit(url).query)["scope"] == ["mcp offline_access"]


# --- hardened HTTP -------------------------------------------------------------------------


async def test_redirects_are_never_followed(settings, stub):
    stub.mock.get(PRM_URL).mock(
        return_value=httpx.Response(302, headers={"location": "https://evil.example/prm"})
    )
    with pytest.raises(oauth.OAuthError, match="redirect"):
        await discover(settings)
    assert not any("evil.example" in str(c.request.url) for c in stub.mock.calls)


async def test_an_oversized_answer_is_refused_by_content_length(settings, stub):
    stub.mock.get(PRM_URL).mock(
        return_value=httpx.Response(
            200,
            content=b"{}",
            headers={"content-type": "application/json", "content-length": "70000"},
        )
    )
    with pytest.raises(oauth.OAuthError, match="too large"):
        await discover(settings)


async def test_an_oversized_streamed_answer_is_cut_off(settings, stub):
    async def chunks():
        yield b'{"resource": "'
        for _ in range(80):
            yield b"a" * 1024

    stub.mock.get(PRM_URL).mock(
        return_value=httpx.Response(
            200, content=chunks(), headers={"content-type": "application/json"}
        )
    )
    with pytest.raises(oauth.OAuthError, match="too large"):
        await discover(settings)


async def test_a_non_json_answer_is_refused(settings, stub):
    stub.mock.get(PRM_URL).mock(
        return_value=httpx.Response(
            200, text="<html>hi</html>", headers={"content-type": "text/html"}
        )
    )
    with pytest.raises(oauth.OAuthError, match="not a JSON object"):
        await discover(settings)


async def test_a_network_failure_message_carries_nothing_from_the_error(settings, stub):
    stub.mock.get(PRM_URL).mock(side_effect=httpx.ConnectError("boom secret-host"))
    with pytest.raises(oauth.OAuthError) as exc:
        await discover(settings)
    assert "secret-host" not in str(exc.value)


async def test_a_non_default_issuer_list_is_honoured(stub):
    custom = Settings(
        _env_file=None, environment="test", tamtam_oauth_allowed_issuers=["https://other.example"]
    )
    with pytest.raises(oauth.OAuthError, match="not in the allowed list"):
        await discover(custom)


# --- registration --------------------------------------------------------------------------


async def test_registration_sends_a_public_client_and_returns_the_id(settings, stub):
    async with oauth.new_client() as client:
        meta = await oauth.discover(client, settings)
        registered = await oauth.register_client(client, meta, REDIRECT)
    assert registered.client_id == CLIENT_ID and registered.client_secret is None
    assert stub.register_calls == [
        {
            "client_name": "DataForce (local)",
            "redirect_uris": [REDIRECT],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }
    ]


async def test_redirect_uri_uses_the_ui_port():
    s = Settings(_env_file=None, environment="test", ui_port=9123)
    assert oauth.redirect_uri_for(s) == "http://127.0.0.1:9123/api/connectors/tamtam/callback"


async def test_registration_refusals(settings, stub):
    async with oauth.new_client() as client:
        meta = await oauth.discover(client, settings)
        stub.mock.post(f"{ISSUER}/register").mock(return_value=httpx.Response(400, json={}))
        with pytest.raises(oauth.OAuthError, match="refused"):
            await oauth.register_client(client, meta, REDIRECT)
        stub.mock.post(f"{ISSUER}/register").mock(return_value=httpx.Response(201, json={}))
        with pytest.raises(oauth.OAuthError, match="client_id"):
            await oauth.register_client(client, meta, REDIRECT)
        stub.mock.post(f"{ISSUER}/register").mock(
            return_value=httpx.Response(
                201, json={"client_id": "x", "redirect_uris": ["https://e/"]}
            )
        )
        with pytest.raises(oauth.OAuthError, match="redirect URI"):
            await oauth.register_client(client, meta, REDIRECT)


async def test_no_registration_endpoint_means_no_registration(settings, stub):
    del stub.as_meta["registration_endpoint"]
    async with oauth.new_client() as client:
        meta = await oauth.discover(client, settings)
        with pytest.raises(oauth.OAuthError, match="registration"):
            await oauth.register_client(client, meta, REDIRECT)


# --- PKCE and authorize URL ----------------------------------------------------------------


def test_pkce_challenge_is_s256_of_a_long_verifier():
    verifier, challenge = oauth.new_pkce()
    assert 43 <= len(verifier) <= 128
    digest = hashlib.sha256(verifier.encode()).digest()
    assert challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert oauth.new_pkce()[0] != verifier
    assert len(oauth.new_state()) >= 43 and oauth.new_state() != oauth.new_state()


async def test_authorize_url(settings, stub):
    meta = await discover(settings)
    url = oauth.build_authorize_url(
        meta,
        client_id=CLIENT_ID,
        redirect_uri=REDIRECT,
        state="st",
        challenge="ch",
        resource=MCP_URL,
    )
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{ISSUER}/authorize"
    q = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert q == {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT,
        "state": "st",
        "code_challenge": "ch",
        "code_challenge_method": "S256",
        "resource": MCP_URL,
    }


# --- tokens --------------------------------------------------------------------------------


async def exchange(settings, **kw):
    async with oauth.new_client() as client:
        meta = await oauth.discover(client, settings)
        return await oauth.exchange_code(
            client,
            meta,
            client_id=CLIENT_ID,
            client_secret=kw.get("client_secret"),
            code=CODE,
            verifier="v" * 64,
            redirect_uri=REDIRECT,
            resource=MCP_URL,
        )


async def test_code_exchange_form_and_result(settings, stub):
    tokens = await exchange(settings)
    assert tokens.access_token == ACCESS_1 and tokens.refresh_token == REFRESH_1
    assert tokens.expires_at and timedelta(minutes=59) < tokens.expires_at - datetime.now(UTC)
    assert stub.token_calls == [
        {
            "grant_type": "authorization_code",
            "code": CODE,
            "redirect_uri": REDIRECT,
            "client_id": CLIENT_ID,
            "code_verifier": "v" * 64,
            "resource": MCP_URL,
        }
    ]


async def test_client_secret_is_sent_when_registration_returned_one(settings, stub):
    await exchange(settings, client_secret="shh")
    assert stub.token_calls[0]["client_secret"] == "shh"


@pytest.mark.parametrize("token_type", ["mac", "", None, 5])
async def test_a_token_that_is_not_bearer_is_refused(settings, stub, token_type):
    stub.code_reply = (200, {"access_token": "a", "token_type": token_type, "expires_in": 60})
    with pytest.raises(oauth.OAuthError, match="bearer"):
        await exchange(settings)


async def test_token_type_is_case_insensitive(settings, stub):
    stub.code_reply = (200, {"access_token": "a", "token_type": "BEARER"})
    tokens = await exchange(settings)
    assert tokens.expires_at is None and tokens.refresh_token is None


@pytest.mark.parametrize("bad", [{"access_token": ""}, {"access_token": 5}, {}])
async def test_a_missing_access_token_is_refused(settings, stub, bad):
    stub.code_reply = (200, {"token_type": "Bearer", **bad})
    with pytest.raises(oauth.OAuthError, match="access_token"):
        await exchange(settings)


@pytest.mark.parametrize("bad", [-1, 0, "soon", True])
async def test_an_invalid_expires_in_is_refused(settings, stub, bad):
    stub.code_reply = (
        200,
        {"access_token": "a", "token_type": "Bearer", "expires_in": bad},
    )
    with pytest.raises(oauth.OAuthError):
        await exchange(settings)


async def test_token_endpoint_oversized_and_redirect_are_refused(settings, stub):
    async with oauth.new_client() as client:
        meta = await oauth.discover(client, settings)
    stub.mock.post(f"{ISSUER}/token").mock(
        return_value=httpx.Response(
            200,
            content=b'{"a":"' + b"a" * 70000 + b'"}',
            headers={"content-type": "application/json"},
        )
    )
    with pytest.raises(oauth.OAuthError, match="too large"):
        await exchange(settings)
    stub.mock.post(f"{ISSUER}/token").mock(
        return_value=httpx.Response(307, headers={"location": "https://evil.example/t"})
    )
    with pytest.raises(oauth.OAuthError, match="redirect"):
        await exchange(settings)
    assert meta.token_endpoint


async def test_invalid_grant_is_its_own_error(settings, stub):
    stub.code_reply = (400, {"error": "invalid_grant", "error_description": "secret detail"})
    with pytest.raises(oauth.InvalidGrant) as exc:
        await exchange(settings)
    assert "secret detail" not in str(exc.value)


async def test_other_token_errors_do_not_echo_the_body(settings, stub):
    stub.code_reply = (500, {"error": "server_error", "error_description": "stack trace here"})
    with pytest.raises(oauth.OAuthError) as exc:
        await exchange(settings)
    assert "stack trace" not in str(exc.value) and not isinstance(exc.value, oauth.InvalidGrant)


async def refresh(settings, token=REFRESH_1):
    async with oauth.new_client() as client:
        meta = await oauth.discover(client, settings)
        return await oauth.refresh_tokens(
            client,
            meta,
            client_id=CLIENT_ID,
            client_secret=None,
            refresh_token=token,
            resource=MCP_URL,
        )


async def test_refresh_rotates_the_refresh_token(settings, stub):
    tokens = await refresh(settings)
    assert (tokens.access_token, tokens.refresh_token) == (ACCESS_2, REFRESH_2)
    assert stub.token_calls[-1] == {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_1,
        "client_id": CLIENT_ID,
        "resource": MCP_URL,
    }


async def test_refresh_keeps_the_old_refresh_token_when_not_rotated(settings, stub):
    stub.refresh_reply = (200, {"access_token": "new", "token_type": "Bearer", "expires_in": 60})
    assert (await refresh(settings)).refresh_token == REFRESH_1


async def test_refresh_invalid_grant(settings, stub):
    stub.refresh_reply = (400, {"error": "invalid_grant"})
    with pytest.raises(oauth.InvalidGrant):
        await refresh(settings)


def test_needs_refresh_margin_is_sixty_seconds():
    now = datetime.now(UTC)
    assert oauth.needs_refresh(now + timedelta(seconds=30))
    assert oauth.needs_refresh(now - timedelta(seconds=1))
    assert not oauth.needs_refresh(now + timedelta(seconds=120))
    assert not oauth.needs_refresh(None)


async def test_revocation_only_when_advertised(settings, stub):
    async with oauth.new_client() as client:
        meta = await oauth.discover(client, settings)
        await oauth.revoke_token(client, meta, "t", CLIENT_ID)
        assert stub.revoke_calls == []  # TamTam advertises none
    stub.as_meta["revocation_endpoint"] = f"{ISSUER}/revoke"
    async with oauth.new_client() as client:
        meta = await oauth.discover(client, settings)
        await oauth.revoke_token(client, meta, "tok", CLIENT_ID)
    assert stub.revoke_calls == [{"token": "tok", "client_id": CLIENT_ID}]


async def test_an_infinite_expires_in_is_refused(settings, stub):
    stub.mock.post(f"{ISSUER}/token").mock(
        return_value=httpx.Response(
            200,
            content=b'{"access_token":"a","token_type":"Bearer","expires_in":1e999}',
            headers={"content-type": "application/json"},
        )
    )
    with pytest.raises(oauth.OAuthError, match="expires_in"):
        await exchange(settings)
