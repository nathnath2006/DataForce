"""Persistence-boundary scrubbing (SR3-06).

PostgreSQL refuses a NUL character in `text` / `jsonb` and a lone UTF-16 surrogate in JSON, and
psycopg cannot even encode a lone surrogate. LLM output, page excerpts and registry fields are
untrusted, so one such character used to make a whole company unsaveable (and cost one more LLM
call at every refresh). The services therefore strip those characters from anything that came
from outside before it is written. Nothing else is changed: evidence quotes stay verbatim.
"""

from __future__ import annotations

import re
from typing import Any

# U+0000 and the surrogate block U+D800-U+DFFF (never valid in well-formed UTF-8).
_BAD_CHARS = re.compile("[\x00\ud800-\udfff]")


def scrub_text(value: str) -> str:
    """`value` without NUL bytes and lone surrogates."""
    return _BAD_CHARS.sub("", value)


def scrub_optional(value: str | None) -> str | None:
    return None if value is None else scrub_text(value)


def scrub_json(value: Any) -> Any:
    """Recursively scrub every string (dict keys included) inside dicts, lists and tuples.
    Numbers, booleans and None are returned as they are; the input is not modified."""
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {
            (scrub_text(k) if isinstance(k, str) else k): scrub_json(v) for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [scrub_json(v) for v in value]
    return value
