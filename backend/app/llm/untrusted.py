"""Handling of untrusted text (scraped pages, free-text titles...) before it reaches an LLM.

sanitize_text(text)      NFKC, drop control/format chars, neutralize source-tag look-alikes;
                         idempotent (SR2-16)
wrap_sources(sources)    {id: text} -> `<source id="...">...</source>` blocks, data only
"""

from __future__ import annotations

import re
import unicodedata

# "<source", "</source", "< / source"...: the only sequences that could open or close our blocks.
# Whitespace gaps are bounded (SR5-01): no nested/adjacent unbounded quantifiers, so it is linear.
_SOURCE_TAG_RE = re.compile(r"<(\s{0,16}/?\s{0,16}source)", re.IGNORECASE)
# Per-text input cap (SR5-01). Longer inputs are truncated (never passed on whole), so the cost of
# sanitising is bounded no matter what a scraped page or note contains.
MAX_SANITIZE_CHARS = 200_000
# control, format (bidi / zero-width / Unicode tag characters), surrogate, private use
_DROP_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co"})
_TO_SPACE = frozenset("\t\x0b\x0c")
_TO_NEWLINE = frozenset("  \x85")
_MAX_SANITIZE_PASSES = 8
_ID_BAD_RE = re.compile(r"[^A-Za-z0-9_.:\-]")


def _sanitize_once(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    out: list[str] = []
    for ch in t:
        if ch == "\n":
            out.append(ch)
        elif ch in _TO_SPACE:
            out.append(" ")
        elif ch in _TO_NEWLINE:
            out.append("\n")
        elif unicodedata.category(ch) in _DROP_CATEGORIES:
            continue
        else:
            out.append(ch)
    t = "".join(out)
    previous = None
    while previous != t:
        previous = t
        t = _SOURCE_TAG_RE.sub(r"&lt;\1", t)
    return t


def sanitize_text(text: str) -> str:
    """Make untrusted text safe to embed inside a delimited data block.

    NFKC first (fullwidth '＜/source＞' becomes '</source>' before we look for it), then drop
    control / format / private-use characters, then neutralize source-tag sequences. The whole
    transform is repeated until stable, so it is idempotent (SR2-16). Look-alike letters from
    other scripts are not folded: they are not a delimiter (documented residual).
    """
    t = text[:MAX_SANITIZE_CHARS]
    for _ in range(_MAX_SANITIZE_PASSES):
        nxt = _sanitize_once(t)
        if nxt == t:
            return t
        t = nxt
    return t


def safe_source_id(source_id: str) -> str:
    """An attribute-safe id: sanitized, restricted charset, bounded length (SR2-08)."""
    cleaned = _ID_BAD_RE.sub("_", sanitize_text(source_id))[:80]
    return cleaned or "_"


def wrap_sources(sources: dict[str, str]) -> str:
    """Render `{source_id: text}` as `<source id="...">text</source>` blocks.

    Ids are restricted to a safe charset (colliding ids get a numeric suffix) so attacker text
    never lands in an attribute; bodies are sanitized so they cannot close their own block.
    The caller's system prompt must say the blocks are data, never instructions.
    """
    blocks: list[str] = []
    seen: set[str] = set()
    for raw_id, text in sources.items():
        sid = base = safe_source_id(raw_id)
        n = 2
        while sid in seen:
            sid = f"{base}_{n}"
            n += 1
        seen.add(sid)
        blocks.append(f'<source id="{sid}">\n{sanitize_text(text)}\n</source>')
    return "\n\n".join(blocks)
