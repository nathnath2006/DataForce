"""Shared pieces of the mailbox providers: the metadata record, hardened JSON GET, address and
text cleaning. Nothing here logs an address, a subject, a token or a body."""

from __future__ import annotations

import asyncio
import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import getaddresses
from html.parser import HTMLParser
from typing import Any

import httpx

from app.connectors.oauth import OAuthError

MAX_JSON_BYTES = 2 * 1024 * 1024  # a full message (Gmail format=full) can be large
MAX_ADDRESSES = 20
SNIPPET_MAX = 200
SUBJECT_MAX = 300
BODY_MAX = 10_000
_ADDR = re.compile(r"^[^@\s<>,;\"]{1,64}@[^@\s<>,;\"]{1,255}$")


class MailboxApiError(OAuthError):
    """The mail provider refused or failed a request. Fixed message, nothing the server sent."""


class Unauthorized(MailboxApiError):
    """HTTP 401: the access token is no longer good."""


@dataclass(frozen=True)
class MessageMeta:
    id: str
    thread_id: str | None
    sender: str
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    sent_at: datetime | None = None
    subject: str = ""
    snippet: str = ""


def clean_addr(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().strip("<>").lower()
    return v if len(v) <= 320 and _ADDR.match(v) else None


def parse_address_list(raw: str | None) -> list[str]:
    out: list[str] = []
    for _, addr in getaddresses([raw or ""]):
        a = clean_addr(addr)
        if a and a not in out:
            out.append(a)
    return out[:MAX_ADDRESSES]


def clip(text: str | None, limit: int) -> str:
    text = re.sub(r"\s+", " ", html.unescape(text or "")).strip()
    return text[:limit]


RAW_HTML_MAX = 2_000_000  # the provider's JSON is capped at 2 MB anyway
_SKIP = frozenset({"script", "style", "head", "title"})
_BREAKS = frozenset({"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"})


class _Text(HTMLParser):
    """Collects text outside script/style/head; block ends become line breaks. HTMLParser works
    in linear time, unlike regexes over unterminated tags (200k chars of "<" took 15 s)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.size = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self.skip += 1
        elif tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in _BREAKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip and self.size < BODY_MAX * 2:
            self.parts.append(data)
            self.size += len(data)


def html_to_text(raw: str) -> str:
    """Plain text from an HTML body: scripts and styles dropped, tags removed, entities decoded.
    The result is only ever rendered as text (React escapes it)."""
    parser = _Text()
    parser.feed(raw[:RAW_HTML_MAX])
    parser.close()
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def cap_body(text: str) -> str:
    text = text.replace("\x00", "").strip()
    return text[:BODY_MAX]


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    token: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """GET with the bearer token, no redirects, a size cap and a timeout. 401 -> Unauthorized."""
    try:
        async with asyncio.timeout(30):
            async with client.stream(
                "GET",
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}", **(headers or {})},
            ) as response:
                status = response.status_code
                buffer = bytearray()
                async for chunk in response.aiter_bytes():
                    buffer += chunk
                    if len(buffer) > MAX_JSON_BYTES:
                        raise MailboxApiError("the mail provider's answer is too large")
    except MailboxApiError:
        raise
    except (httpx.HTTPError, TimeoutError):
        raise MailboxApiError("the mail provider could not be reached") from None
    if status == 401:
        raise Unauthorized("the mail provider rejected the access token")
    if status != 200:
        raise MailboxApiError(f"the mail provider refused the request (HTTP {status})")
    try:
        body = json.loads(bytes(buffer))
    except (ValueError, RecursionError):
        raise MailboxApiError("the mail provider's answer is not JSON") from None
    if not isinstance(body, dict):
        raise MailboxApiError("the mail provider's answer is not a JSON object")
    return body
