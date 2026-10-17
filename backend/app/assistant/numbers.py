"""Number extraction and normalisation for the post-check of assistant answers.

`number_values(text)` returns every candidate value of every number written in `text`, so
"1 234,5 EUR", "1,234.5", "12 %", "40k" and "2.5M" can be compared with the context.
`unverified_numbers(answer, context_values)` lists the answer's numbers that match nothing.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# "1 234 567,89" (space / nbsp / narrow nbsp groups of 3) or a plain run with . , separators.
_NUM_RE = re.compile(
    r"(?<![\w.,])(?P<num>\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)*)"
    r"(?P<tail>\s?(?:%|[kKmM](?![A-Za-z0-9À-ɏ]))?)"
)
_REF_RE = re.compile(r"\[\s*[FDCNM]\d+(?:\s*[,;]\s*[FDCNM]\d+)*\s*\]")
_LIST_MARKER_RE = re.compile(r"(?m)^\s*\d{1,2}[.)]\s")
_MAX_DIGITS = 18


def _to_decimals(raw: str) -> list[Decimal]:
    s = re.sub(r"[   ]", "", raw)
    cands: list[str] = []
    if "." in s and "," in s:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        thou = "," if dec == "." else "."
        cands.append(s.replace(thou, "").replace(dec, "."))
    elif "." in s or "," in s:
        sep = "." if "." in s else ","
        parts = s.split(sep)
        if len(parts) > 2:
            cands.append("".join(parts))  # 1,234,567
        else:
            head, tail = parts
            cands.append(f"{head}.{tail}")  # decimal reading
            if len(tail) == 3 and 1 <= len(head) <= 3 and head != "0":
                cands.append(head + tail)  # thousands reading: 1,234 / 1.234
    else:
        cands.append(s)
    out: list[Decimal] = []
    for c in cands:
        if len(c.replace(".", "")) > _MAX_DIGITS:
            continue
        try:
            out.append(Decimal(c))
        except InvalidOperation:
            continue
    return out


def _canon(d: Decimal) -> Decimal:
    return d.normalize() if d != 0 else Decimal(0)


def extract_numbers(text: str) -> list[set[Decimal]]:
    """One set of candidate values per number found in `text` (scaled by k / M when suffixed)."""
    found: list[set[Decimal]] = []
    for m in _NUM_RE.finditer(text):
        values = _to_decimals(m.group("num"))
        tail = m.group("tail").strip().lower()
        scale = {"k": Decimal(1000), "m": Decimal(1_000_000)}.get(tail)
        cands = {_canon(v * scale) for v in values} if scale else {_canon(v) for v in values}
        if cands:
            found.append(cands)
    return found


def number_values(text: str) -> set[Decimal]:
    """Every value any number of `text` can stand for (used to build the context's number set)."""
    out: set[Decimal] = set()
    for cands in extract_numbers(text):
        out |= cands
    return out


def strip_non_claims(answer: str) -> str:
    """Remove what is not a numeric claim: the [F3] reference markers and 1. / 2) list markers."""
    return _LIST_MARKER_RE.sub("\n", _REF_RE.sub(" ", answer))


def unverified_numbers(answer: str, context_values: set[Decimal]) -> list[str]:
    """The numbers of `answer` that match no number of the context, as written, in order."""
    text = strip_non_claims(answer)
    bad: list[str] = []
    for m in _NUM_RE.finditer(text):
        values = _to_decimals(m.group("num"))
        tail = m.group("tail").strip().lower()
        scale = {"k": Decimal(1000), "m": Decimal(1_000_000)}.get(tail)
        cands = {_canon(v * scale) if scale else _canon(v) for v in values}
        if cands and not (cands & context_values):
            written = m.group(0).strip()
            if written not in bad:
                bad.append(written)
    return bad[:50]
