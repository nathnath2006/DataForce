"""Gmail (read-only). Scopes: `openid email` (the signed-in address) and `gmail.readonly`.

The OAuth client is a Google "Desktop app" client: PKCE S256, loopback redirect, and a client
secret that Google documents as not confidential but still requires at the token endpoint.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from app.connectors import oauth
from app.connectors.mailbox import base
from app.connectors.mailbox.base import MessageMeta

NAME = "gmail"
LABEL = "Gmail"
SCOPES = "openid email https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
PAGE_SIZE = 100
CONCURRENCY = 8
_HEADERS = ["From", "To", "Cc", "Subject", "Date"]


def redirect_uri(settings: Any, host: str | None = None) -> str:
    return oauth.redirect_uri_for(settings, host).replace("/connectors/tamtam/", "/mailbox/")


def authorize_url(
    settings: Any, *, client_id: str, redirect: str, state: str, challenge: str
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",  # a refresh token
        "prompt": "consent",  # Google sends the refresh token only on a consent screen
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(
    client: httpx.AsyncClient,
    settings: Any,
    *,
    client_id: str,
    client_secret: str | None,
    code: str,
    verifier: str,
    redirect: str,
) -> oauth.TokenSet:
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    return await _token(client, form, client_secret, old_refresh=None)


async def refresh(
    client: httpx.AsyncClient,
    settings: Any,
    *,
    client_id: str,
    client_secret: str | None,
    refresh_token: str,
) -> oauth.TokenSet:
    """Google keeps the refresh token (no rotation); a rotated one would replace it anyway."""
    form = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id}
    return await _token(client, form, client_secret, old_refresh=refresh_token)


async def _token(
    client: httpx.AsyncClient, form: dict[str, str], secret: str | None, old_refresh: str | None
) -> oauth.TokenSet:
    meta = oauth.ServerMetadata(
        issuer="https://accounts.google.com",
        authorization_endpoint=AUTH_URL,
        token_endpoint=TOKEN_URL,
        registration_endpoint=None,
        revocation_endpoint=REVOKE_URL,
        scope=None,
    )
    return await oauth._token_request(
        client, meta, form, client_secret=secret, old_refresh=old_refresh
    )


async def account_email(client: httpx.AsyncClient, token: str) -> str:
    body = await base.get_json(client, USERINFO_URL, token)
    email = base.clean_addr(body.get("email") if isinstance(body.get("email"), str) else None)
    if email is None:
        raise base.MailboxApiError("the mail provider did not return the account address")
    return email


async def revoke(client: httpx.AsyncClient, token: str) -> None:
    try:
        await client.post(REVOKE_URL, data={"token": token})
    except httpx.HTTPError:
        pass


def _header(headers: list[dict[str, Any]], name: str) -> str | None:
    for h in headers:
        if isinstance(h, dict) and str(h.get("name", "")).lower() == name.lower():
            value = h.get("value")
            return value if isinstance(value, str) else None
    return None


def _meta(raw: dict[str, Any]) -> MessageMeta | None:
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
    headers = payload.get("headers") if isinstance(payload.get("headers"), list) else []
    sender = base.parse_address_list(_header(headers, "From"))
    msg_id = raw.get("id")
    if not sender or not isinstance(msg_id, str):
        return None
    try:
        sent = datetime.fromtimestamp(int(raw["internalDate"]) / 1000, UTC)
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        return None
    thread = raw.get("threadId")
    return MessageMeta(
        id=msg_id,
        thread_id=thread if isinstance(thread, str) else None,
        sender=sender[0],
        to=base.parse_address_list(_header(headers, "To")),
        cc=base.parse_address_list(_header(headers, "Cc")),
        sent_at=sent,
        subject=base.clip(_header(headers, "Subject"), base.SUBJECT_MAX),
        snippet=base.clip(raw.get("snippet") if isinstance(raw.get("snippet"), str) else "", 200),
    )


async def list_messages(
    client: httpx.AsyncClient, token: str, *, since: datetime, limit: int
) -> AsyncIterator[list[MessageMeta]]:
    """Pages of metadata, newest first, at most `limit` messages in all."""
    sem = asyncio.Semaphore(CONCURRENCY)
    page_token: str | None = None
    seen = 0

    async def one(msg_id: str) -> MessageMeta | None:
        async with sem:
            raw = await base.get_json(
                client,
                f"{API}/messages/{msg_id}",
                token,
                params=[("format", "metadata")] + [("metadataHeaders", h) for h in _HEADERS],  # type: ignore[arg-type]
            )
        return _meta(raw)

    while seen < limit:
        params: dict[str, Any] = {
            "q": f"after:{int(since.timestamp())}",
            "maxResults": min(PAGE_SIZE, limit - seen),
        }
        if page_token:
            params["pageToken"] = page_token
        listing = await base.get_json(client, f"{API}/messages", token, params=params)
        ids = [
            m["id"]
            for m in listing.get("messages", [])
            if isinstance(m, dict) and isinstance(m.get("id"), str)
        ]
        if not ids:
            return
        seen += len(ids)
        metas = await asyncio.gather(*(one(i) for i in ids))
        yield [m for m in metas if m is not None]
        nxt = listing.get("nextPageToken")
        page_token = nxt if isinstance(nxt, str) and nxt else None
        if page_token is None:
            return


def _walk(part: dict[str, Any], plain: list[str], markup: list[str], depth: int = 0) -> None:
    if depth > 12:
        return
    mime = str(part.get("mimeType", ""))
    data = part.get("body", {}).get("data") if isinstance(part.get("body"), dict) else None
    if isinstance(data, str) and mime in ("text/plain", "text/html"):
        try:
            text = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                "utf-8", errors="replace"
            )
        except (ValueError, TypeError):
            text = ""
        (plain if mime == "text/plain" else markup).append(text)
    for sub in part.get("parts", []) if isinstance(part.get("parts"), list) else []:
        if isinstance(sub, dict):
            _walk(sub, plain, markup, depth + 1)


async def fetch_body(client: httpx.AsyncClient, token: str, message_id: str) -> str:
    """Plain text of the message, capped. Text parts are preferred; HTML is converted."""
    raw = await base.get_json(
        client, f"{API}/messages/{message_id}", token, params={"format": "full"}
    )
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
    plain: list[str] = []
    markup: list[str] = []
    _walk(payload, plain, markup)
    text = "\n".join(plain).strip() or base.html_to_text("\n".join(markup))
    return base.cap_body(text)
