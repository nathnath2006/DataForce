"""Input checks shared by the services (SR3-11): defense in depth for writers that will exist in
M2 (API, MCP server), after the YAML / CLI edge that validates today."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

MAX_URL_CHARS = 2048
_CONTROL_OR_SPACE = re.compile(r"[\x00-\x20\x7f-\x9f]")


def is_http_url(value: str) -> bool:
    """True for an absolute http(s) URL with a host, no whitespace / control characters and a
    sane length. Rejects `javascript:`, `data:`, `file:`, relative and scheme-less values (a
    stored `source_url` rendered as an href would otherwise be a stored-XSS sink)."""
    if not value or len(value) > MAX_URL_CHARS or _CONTROL_OR_SPACE.search(value):
        return False
    try:
        parts = urlsplit(value)
        return parts.scheme in ("http", "https") and bool(parts.hostname)
    except ValueError:
        return False
