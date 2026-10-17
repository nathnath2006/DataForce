"""Deterministic verbatim check of LLM-supplied quotes (SR2-02 hardening).

A quote is `verified` only if, after normalization (sanitize, NFKC, unified quotes/dashes,
casefold, whitespace COLLAPSED to one space, never deleted), it is long enough, occurs on word
boundaries inside the named source, and its passage backs at most `MAX_CLAIMS_PER_QUOTE` claims.
This proves "the string is in the source", not that it supports the claim.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from app.llm.untrusted import sanitize_text

MIN_QUOTE_CHARS = 20
MIN_QUOTE_WORDS = 3
MAX_CLAIMS_PER_QUOTE = 2
MAX_QUOTE_CHARS = 300


class VerifiedQuote(BaseModel):
    claim: str
    quote: str
    source_id: str
    verified: bool


_QUOTE_MAP = str.maketrans(
    {
        **dict.fromkeys("‘’‚‛′ʼ`´", "'"),
        **dict.fromkeys("“”„‟″«»", '"'),
        **dict.fromkeys("‐‑‒–—―−", "-"),
    }
)
_EDGE_NOISE_RE = re.compile(r"^(?:\.{3,}|[\"'\s])+|(?:\.{3,}|[\"'\s])+$")
_WS_RE = re.compile(r"\s+")


def match_key(text: str) -> str:
    t = sanitize_text(text).translate(_QUOTE_MAP).casefold()
    return _WS_RE.sub(" ", t).strip()


def _quote_key(quote: str) -> str:
    return _EDGE_NOISE_RE.sub("", match_key(quote)).strip()


def _word_count(key: str) -> int:
    return sum(1 for w in key.split() if any(ch.isalnum() for ch in w))


def _on_word_boundaries(haystack: str, needle: str) -> bool:
    start = 0
    while (i := haystack.find(needle, start)) != -1:
        j = i + len(needle)
        starts_ok = not (needle[0].isalnum() and i > 0 and haystack[i - 1].isalnum())
        ends_ok = not (needle[-1].isalnum() and j < len(haystack) and haystack[j].isalnum())
        if starts_ok and ends_ok:
            return True
        start = i + 1
    return False


def _get(q: Any, name: str, default: str = "") -> str:
    v = q.get(name, default) if isinstance(q, Mapping) else getattr(q, name, default)
    return v if isinstance(v, str) else default


def verify_quotes(quotes: Sequence[Any], sources: Mapping[str, str]) -> list[VerifiedQuote]:
    """One `VerifiedQuote` per input, in order.

    Each input has `quote` and `source_id` (pydantic object or dict) and optionally `claim`
    (defaults to ""). Unknown source, too short (< 20 chars or < 3 words), over 300 chars, or a
    passage already backing 2 other claims => `verified=False`.
    """
    haystacks = {sid: match_key(text) for sid, text in sources.items()}
    backing: dict[str, set[str]] = {}
    out: list[VerifiedQuote] = []
    for q in quotes:
        claim, sid = _get(q, "claim"), _get(q, "source_id")
        # Length cap BEFORE any sanitising (SR5-01): an oversized quote is cut, never processed.
        raw = _get(q, "quote")[: MAX_QUOTE_CHARS * 4].strip()
        claim_key = claim.strip().lower()
        verified = False
        if raw and len(raw) <= MAX_QUOTE_CHARS and sid in haystacks:
            key = _quote_key(raw)
            if (
                len(key) >= MIN_QUOTE_CHARS
                and _word_count(key) >= MIN_QUOTE_WORDS
                and _on_word_boundaries(haystacks[sid], key)
            ):
                claims = backing.setdefault(key, set())
                if claim_key in claims or len(claims) < MAX_CLAIMS_PER_QUOTE:
                    claims.add(claim_key)
                    verified = True
        out.append(
            VerifiedQuote(
                claim=claim,
                quote=sanitize_text(raw)[:MAX_QUOTE_CHARS],
                source_id=sid,
                verified=verified,
            )
        )
    return out
