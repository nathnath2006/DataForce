"""OAuth 2.1 client for a remote MCP server (docs/UI-CONTRACT.md section 4).

Discovery (RFC 9728 then RFC 8414), dynamic client registration (RFC 7591), PKCE S256, the
authorization URL, the code exchange and the refresh. Every answer from a server is untrusted:

* requests never follow redirects, time out after 10 s and are read through a 64 KB cap;
* the authorization server must be in `tamtam_oauth_allowed_issuers`, its `issuer` must be the
  one we asked for, and every endpoint must be https on the issuer's own origin, so a tampered
  metadata document cannot send the browser, the code or a token anywhere else;
* error messages are fixed strings: nothing a server sent is echoed, and no token, verifier,
  client secret or authorization code is ever put in a message or a log line.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from app.config import Settings
from app.enrichment.errors import EnrichmentError

MAX_RESPONSE_BYTES = 64 * 1024
REQUEST_TIMEOUT_S = 10.0
REFRESH_MARGIN_S = 60
MAX_EXPIRES_IN_S = 365 * 24 * 3600
_MAX_TOKEN_CHARS = 8192
CLIENT_NAME = "DataForce (local)"


class OAuthError(EnrichmentError):
    """The OAuth exchange was refused or went wrong. The message is a fixed string."""


class InvalidGrant(OAuthError):
    """The token endpoint answered `invalid_grant`: the refresh token / code is no longer good."""


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(REQUEST_TIMEOUT_S),
        headers={"Accept": "application/json", "Accept-Encoding": "identity"},
    )


# --- hardened HTTP --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Reply:
    status: int
    body: dict[str, Any] | None  # None: not JSON (only tolerated on non-2xx)


async def _request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    form: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> _Reply:
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT_S):
            async with client.stream(method, url, data=form, json=payload) as response:
                status = response.status_code
                if 300 <= status < 400:
                    raise OAuthError("the server answered with a redirect, which is refused")
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
                    raise OAuthError("the server's answer is too large")
                buffer = bytearray()
                async for chunk in response.aiter_bytes():
                    buffer += chunk
                    if len(buffer) > MAX_RESPONSE_BYTES:
                        raise OAuthError("the server's answer is too large")
                ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
    except OAuthError:
        raise
    except (httpx.HTTPError, TimeoutError):
        raise OAuthError("the server could not be reached") from None
    is_json = ctype == "application/json" or ctype.endswith("+json")
    body: dict[str, Any] | None = None
    if is_json:
        try:
            parsed = json.loads(bytes(buffer))
        except (ValueError, RecursionError):
            parsed = None
        body = parsed if isinstance(parsed, dict) else None
    if 200 <= status < 300 and body is None:
        raise OAuthError("the server's answer is not a JSON object")
    return _Reply(status, body)


# --- discovery ------------------------------------------------------------------------------


@dataclass(frozen=True)
class ServerMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None
    revocation_endpoint: str | None
    scope: str | None  # the server's scopes_supported, space separated, when it lists any
    iss_required: bool = False  # RFC 9207: the callback must carry `iss`


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def _endpoint(value: Any, issuer: str, name: str) -> str:
    """https, on the issuer's own origin, no credentials, no fragment."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise OAuthError(f"the server's metadata has no valid {name}")
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.fragment
        or _origin(value) != _origin(issuer)
    ):
        raise OAuthError(f"the server's {name} is not an https URL on the issuer's origin")
    return value


def _str_list(value: Any) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    return None


async def discover(client: httpx.AsyncClient, settings: Settings) -> ServerMetadata:
    mcp_url = settings.tamtam_mcp_url
    parts = urlsplit(mcp_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    path = parts.path.rstrip("/")
    candidates = [f"{origin}/.well-known/oauth-protected-resource{path}"] if path else []
    candidates.append(f"{origin}/.well-known/oauth-protected-resource")
    resource_meta: dict[str, Any] | None = None
    for url in candidates:
        reply = await _request(client, "GET", url)
        if reply.status == 200 and reply.body is not None:
            resource_meta = reply.body
            break
    if resource_meta is None:
        raise OAuthError("the server publishes no protected-resource metadata")
    resource = resource_meta.get("resource")
    if not isinstance(resource, str) or resource.rstrip("/") != mcp_url.rstrip("/"):
        raise OAuthError("the protected-resource metadata is about a different resource")
    servers = _str_list(resource_meta.get("authorization_servers")) or []
    allowed = {o.rstrip("/").lower() for o in settings.tamtam_oauth_allowed_issuers}
    issuer = next((s.rstrip("/") for s in servers if s.rstrip("/").lower() in allowed), None)
    if issuer is None:
        raise OAuthError("the authorization server is not in the allowed list")

    reply = await _request(client, "GET", f"{issuer}/.well-known/oauth-authorization-server")
    if reply.status != 200 or reply.body is None:
        raise OAuthError("the authorization server publishes no metadata")
    meta = reply.body
    if meta.get("issuer") != issuer:
        raise OAuthError("the authorization server's issuer does not match")
    methods = _str_list(meta.get("code_challenge_methods_supported")) or []
    if "S256" not in methods:
        raise OAuthError("the authorization server does not support PKCE S256")
    for key, needed in (
        ("response_types_supported", "code"),
        ("grant_types_supported", "authorization_code"),
        ("token_endpoint_auth_methods_supported", "none"),
    ):
        listed = _str_list(meta.get(key))
        if listed is not None and needed not in listed:
            raise OAuthError(f"the authorization server does not support {needed!r} ({key})")
    registration = meta.get("registration_endpoint")
    revocation = meta.get("revocation_endpoint")
    scopes = _str_list(meta.get("scopes_supported"))
    return ServerMetadata(
        issuer=issuer,
        authorization_endpoint=_endpoint(
            meta.get("authorization_endpoint"), issuer, "authorization_endpoint"
        ),
        token_endpoint=_endpoint(meta.get("token_endpoint"), issuer, "token_endpoint"),
        registration_endpoint=(
            _endpoint(registration, issuer, "registration_endpoint") if registration else None
        ),
        revocation_endpoint=(
            _endpoint(revocation, issuer, "revocation_endpoint") if revocation else None
        ),
        scope=(" ".join(s for s in scopes if s and " " not in s)[:1000] or None)
        if scopes
        else None,
        iss_required=meta.get("authorization_response_iss_parameter_supported") is True,
    )


# --- registration (RFC 7591) ----------------------------------------------------------------


@dataclass(frozen=True)
class RegisteredClient:
    client_id: str
    client_secret: str | None


_HOST_RE = re.compile(r"^(127\.0\.0\.1|localhost|\[::1\]):(\d{2,5})$")
_VITE_PORT = 5173


def redirect_uri_for(settings: Settings, host: str | None = None) -> str:
    """The callback URL on the origin the browser is using (so the host-only `df_oauth` cookie
    comes back with it). `host` is the request's Host header; anything outside the loopback
    names on the UI or Vite port falls back to 127.0.0.1 on the UI port.
    Hosted: the public origin."""
    if settings.public_origin:
        return f"{settings.public_origin}/api/connectors/tamtam/callback"
    netloc = f"127.0.0.1:{settings.ui_port}"
    match = _HOST_RE.match((host or "").strip().lower())
    if match and int(match.group(2)) in {settings.ui_port, _VITE_PORT}:
        netloc = match.group(0)
    return f"http://{netloc}/api/connectors/tamtam/callback"


async def register_client(
    client: httpx.AsyncClient, meta: ServerMetadata, redirect_uri: str
) -> RegisteredClient:
    if meta.registration_endpoint is None:
        raise OAuthError("the server does not offer dynamic client registration")
    reply = await _request(
        client,
        "POST",
        meta.registration_endpoint,
        payload={
            "client_name": CLIENT_NAME,
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    body = reply.body
    if reply.status not in (200, 201) or body is None:
        raise OAuthError(f"client registration was refused (HTTP {reply.status})")
    client_id = body.get("client_id")
    if not isinstance(client_id, str) or not client_id or len(client_id) > 512:
        raise OAuthError("client registration returned no valid client_id")
    uris = _str_list(body.get("redirect_uris"))
    if uris is not None and redirect_uri not in uris:
        raise OAuthError("client registration did not keep the redirect URI")
    secret = body.get("client_secret")
    if secret is not None and (not isinstance(secret, str) or len(secret) > _MAX_TOKEN_CHARS):
        raise OAuthError("client registration returned an invalid client_secret")
    return RegisteredClient(client_id, secret or None)


# --- PKCE and the authorization URL ---------------------------------------------------------


def new_state() -> str:
    return secrets.token_urlsafe(32)


def new_pkce() -> tuple[str, str]:
    """(verifier from 64 random bytes, S256 challenge)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_authorize_url(
    meta: ServerMetadata,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    challenge: str,
    resource: str,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": resource,
    }
    if meta.scope:
        params["scope"] = meta.scope
    return f"{meta.authorization_endpoint}?{urlencode(params)}"


# --- tokens ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scope: str | None


def _token_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TOKEN_CHARS:
        raise OAuthError(f"the token endpoint returned no valid {name}")
    return value


def _parse_tokens(body: dict[str, Any], *, old_refresh: str | None) -> TokenSet:
    token_type = body.get("token_type")
    if not isinstance(token_type, str) or token_type.lower() != "bearer":
        raise OAuthError("the token endpoint returned a token that is not a bearer token")
    access = _token_str(body.get("access_token"), "access_token")
    refresh = body.get("refresh_token")
    new_refresh = _token_str(refresh, "refresh_token") if refresh is not None else old_refresh
    expires_at = None
    expires_in = body.get("expires_in")
    if expires_in is not None:
        if (
            isinstance(expires_in, bool)
            or not isinstance(expires_in, int | float)
            or not math.isfinite(expires_in)
            or expires_in <= 0
        ):
            raise OAuthError("the token endpoint returned an invalid expires_in")
        expires_at = datetime.now(UTC) + timedelta(seconds=min(expires_in, MAX_EXPIRES_IN_S))
    scope = body.get("scope")
    return TokenSet(
        access, new_refresh, expires_at, scope[:1000] if isinstance(scope, str) else None
    )


async def _token_request(
    client: httpx.AsyncClient,
    meta: ServerMetadata,
    form: dict[str, str],
    *,
    client_secret: str | None,
    old_refresh: str | None,
) -> TokenSet:
    if client_secret:
        form["client_secret"] = client_secret
    reply = await _request(client, "POST", meta.token_endpoint, form=form)
    if 200 <= reply.status < 300 and reply.body is not None:
        return _parse_tokens(reply.body, old_refresh=old_refresh)
    if reply.body is not None and reply.body.get("error") == "invalid_grant":
        raise InvalidGrant("the token endpoint answered invalid_grant")
    raise OAuthError(f"the token endpoint refused the request (HTTP {reply.status})")


async def exchange_code(
    client: httpx.AsyncClient,
    meta: ServerMetadata,
    *,
    client_id: str,
    client_secret: str | None,
    code: str,
    verifier: str,
    redirect_uri: str,
    resource: str,
) -> TokenSet:
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
        "resource": resource,
    }
    return await _token_request(client, meta, form, client_secret=client_secret, old_refresh=None)


async def refresh_tokens(
    client: httpx.AsyncClient,
    meta: ServerMetadata,
    *,
    client_id: str,
    client_secret: str | None,
    refresh_token: str,
    resource: str,
) -> TokenSet:
    """A rotated refresh token replaces the old one; otherwise the old one is kept."""
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "resource": resource,
    }
    return await _token_request(
        client, meta, form, client_secret=client_secret, old_refresh=refresh_token
    )


def needs_refresh(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    return expires_at - datetime.now(UTC) < timedelta(seconds=REFRESH_MARGIN_S)


async def revoke_token(
    client: httpx.AsyncClient, meta: ServerMetadata, token: str, client_id: str
) -> None:
    """RFC 7009, only when the server advertises a revocation endpoint. The caller ignores
    failures: disconnecting must not depend on the server."""
    if meta.revocation_endpoint is None:
        return
    await _request(
        client, "POST", meta.revocation_endpoint, form={"token": token, "client_id": client_id}
    )
