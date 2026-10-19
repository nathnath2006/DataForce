"""Outlook through Microsoft Graph (read-only). Scopes: `Mail.Read`, `offline_access` and
`User.Read` (the signed-in address). A "Mobile and desktop" public client: PKCE S256, loopback
redirect on `localhost` (Entra matches the host `localhost` and ignores the port)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from app.connectors import oauth
from app.connectors.mailbox import base
from app.connectors.mailbox.base import MessageMeta

NAME = "outlook"
LABEL = "Outlook"
SCOPES = "offline_access Mail.Read User.Read"
GRAPH = "https://graph.microsoft.com/v1.0"
PAGE_SIZE = 50
_SELECT = "id,conversationId,from,toRecipients,ccRecipients,receivedDateTime,subject,bodyPreview"


def _authority(settings: Any) -> str:
    return f"https://login.microsoftonline.com/{settings.mailbox_microsoft_tenant}/oauth2/v2.0"


def redirect_uri(settings: Any, host: str | None = None) -> str:
    # Entra accepts `http://localhost` for desktop clients but not the literal 127.0.0.1.
    return f"http://localhost:{settings.ui_port}/api/mailbox/callback"


def authorize_url(
    settings: Any, *, client_id: str, redirect: str, state: str, challenge: str
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_mode": "query",
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{_authority(settings)}/authorize?{urlencode(params)}"


async def _token(
    client: httpx.AsyncClient,
    settings: Any,
    form: dict[str, str],
    secret: str | None,
    old_refresh: str | None,
) -> oauth.TokenSet:
    form["scope"] = SCOPES
    meta = oauth.ServerMetadata(
        issuer="https://login.microsoftonline.com",
        authorization_endpoint=f"{_authority(settings)}/authorize",
        token_endpoint=f"{_authority(settings)}/token",
        registration_endpoint=None,
        revocation_endpoint=None,
        scope=None,
    )
    return await oauth._token_request(
        client, meta, form, client_secret=secret, old_refresh=old_refresh
    )


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
    return await _token(client, settings, form, client_secret, None)


async def refresh(
    client: httpx.AsyncClient,
    settings: Any,
    *,
    client_id: str,
    client_secret: str | None,
    refresh_token: str,
) -> oauth.TokenSet:
    """Microsoft rotates the refresh token: the new one replaces the old one."""
    form = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id}
    return await _token(client, settings, form, client_secret, refresh_token)


async def account_email(client: httpx.AsyncClient, token: str) -> str:
    body = await base.get_json(
        client, f"{GRAPH}/me", token, params={"$select": "mail,userPrincipalName"}
    )
    for key in ("mail", "userPrincipalName"):
        value = body.get(key)
        email = base.clean_addr(value if isinstance(value, str) else None)
        if email:
            return email
    raise base.MailboxApiError("the mail provider did not return the account address")


async def revoke(client: httpx.AsyncClient, token: str) -> None:
    """The Microsoft identity platform has no simple token revocation endpoint: nothing to do.
    Removing the app's access is done in the account's privacy page."""


def _addresses(items: Any) -> list[str]:
    out: list[str] = []
    for item in items if isinstance(items, list) else []:
        addr = item.get("emailAddress", {}).get("address") if isinstance(item, dict) else None
        clean = base.clean_addr(addr if isinstance(addr, str) else None)
        if clean and clean not in out:
            out.append(clean)
    return out[: base.MAX_ADDRESSES]


def _meta(raw: dict[str, Any]) -> MessageMeta | None:
    frm = raw.get("from")
    sender = _addresses([frm] if isinstance(frm, dict) else [])
    msg_id = raw.get("id")
    when = raw.get("receivedDateTime")
    if not sender or not isinstance(msg_id, str) or not isinstance(when, str):
        return None
    try:
        sent = datetime.fromisoformat(when.replace("Z", "+00:00"))
    except ValueError:
        return None
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=UTC)
    conv = raw.get("conversationId")
    return MessageMeta(
        id=msg_id,
        thread_id=conv if isinstance(conv, str) else None,
        sender=sender[0],
        to=_addresses(raw.get("toRecipients")),
        cc=_addresses(raw.get("ccRecipients")),
        sent_at=sent,
        subject=base.clip(raw.get("subject") if isinstance(raw.get("subject"), str) else "", 300),
        snippet=base.clip(
            raw.get("bodyPreview") if isinstance(raw.get("bodyPreview"), str) else "", 200
        ),
    )


async def list_messages(
    client: httpx.AsyncClient, token: str, *, since: datetime, limit: int
) -> AsyncIterator[list[MessageMeta]]:
    url: str | None = f"{GRAPH}/me/messages"
    params: dict[str, Any] | None = {
        "$select": _SELECT,
        "$filter": f"receivedDateTime ge {since.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "$orderby": "receivedDateTime desc",
        "$top": min(PAGE_SIZE, limit),
    }
    seen = 0
    while url and seen < limit:
        page = await base.get_json(client, url, token, params=params)
        items = [m for m in page.get("value", []) if isinstance(m, dict)][: limit - seen]
        seen += len(items)
        yield [m for m in (_meta(i) for i in items) if m is not None]
        nxt = page.get("@odata.nextLink")
        # A next link is followed only on Graph's own origin: the bearer token goes nowhere else.
        url = (
            nxt if isinstance(nxt, str) and urlsplit(nxt).netloc == "graph.microsoft.com" else None
        )
        if url and not url.startswith("https://"):
            url = None
        params = None


async def fetch_body(client: httpx.AsyncClient, token: str, message_id: str) -> str:
    from urllib.parse import quote

    raw = await base.get_json(
        client,
        f"{GRAPH}/me/messages/{quote(message_id, safe='')}",
        token,
        params={"$select": "body"},
        headers={"Prefer": 'outlook.body-content-type="text"'},
    )
    body = raw.get("body") if isinstance(raw.get("body"), dict) else {}
    content = body.get("content") if isinstance(body.get("content"), str) else ""
    if str(body.get("contentType", "")).lower() == "html":
        content = base.html_to_text(content)
    return base.cap_body(content)
