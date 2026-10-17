"""Number extraction and normalisation for the post-check of assistant answers.

`number_values(text)` returns every candidate value of every number written in `text`, so
"1 234,5 EUR", "1,234.5", "12 %", "40k" and "2.5M" can be compared with the context.
`classify_numbers(answer, verified, noted)` splits the answer's numbers into unverified ones and
ones found only in untrusted notes. Digits glued to letters, scaled words ("3 million", "2,5 M€")
and EN/FR number words ("twelve", "vingt-cinq") are all examined.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# "1 234 567,89" (space / nbsp / narrow nbsp groups of 3) or a plain run with . , separators.
# A currency or letter glued before the digits ("EUR9999") is allowed; only a digit or a
# separator before disqualifies (it is then part of a longer number).
_SCALE_WORDS = r"milliards?|millions?|billions?|thousand|mille|mds?|bn|[kKmM]"
_NUM_RE = re.compile(
    r"(?<![\d.,])(?P<num>\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)*)"
    r"(?P<tail>\s?(?:%|(?:" + _SCALE_WORDS + r")(?![A-Za-z0-9À-ɏ])))?",
    re.IGNORECASE,
)
_SCALES = {
    "k": Decimal(10) ** 3,
    "thousand": Decimal(10) ** 3,
    "mille": Decimal(10) ** 3,
    "m": Decimal(10) ** 6,
    "million": Decimal(10) ** 6,
    "millions": Decimal(10) ** 6,
    "md": Decimal(10) ** 9,
    "mds": Decimal(10) ** 9,
    "bn": Decimal(10) ** 9,
    "billion": Decimal(10) ** 9,
    "billions": Decimal(10) ** 9,
    "milliard": Decimal(10) ** 9,
    "milliards": Decimal(10) ** 9,
}
_REF_RE = re.compile(r"\[\s*[A-Z]\d+(?:\s*[,;]\s*[A-Z]\d+)*\s*\]")  # any ref-shaped marker
_LIST_MARKER_RE = re.compile(r"(?m)^\s*\d{1,2}[.)]\s")
_MAX_DIGITS = 18

# --- number words (EN + FR) ---------------------------------------------------------------
_UNITS = {
    "zero": 0, "zéro": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "sept": 7,
    "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14,
    "quinze": 15, "seize": 16, "vingt": 20, "dozen": 12, "douzaine": 12,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60,
    "septante": 70, "huitante": 80, "octante": 80, "nonante": 90, "quatrevingt": 80,
    "quatrevingts": 80,
}  # fmt: skip
_HUNDRED = {"hundred": 100, "cent": 100, "cents": 100}
_BIG = {
    "thousand": 10**3, "mille": 10**3, "million": 10**6, "millions": 10**6,
    "billion": 10**9, "billions": 10**9, "milliard": 10**9, "milliards": 10**9,
}  # fmt: skip
_WORD_RE = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")
_QV_RE = re.compile(r"quatre[\s-]+vingts?", re.IGNORECASE)
_CONNECTORS = {"and", "et"}


def _word_numbers(text: str) -> list[tuple[str, Decimal]]:
    """(as written, value) for each run of number words, e.g. "twenty-five", "vingt et un".
    Digit numbers (and their "million" style tails) are blanked first: they are judged apart."""
    text = _NUM_RE.sub(lambda m: " " * len(m.group(0)), text)
    text = _QV_RE.sub("quatrevingt", text)
    # tokens with positions; hyphenated words are split into parts
    toks: list[tuple[str, int, int]] = []
    for m in _WORD_RE.finditer(text):
        pos = m.start()
        for part in m.group(0).split("-"):
            toks.append((part.lower(), pos, pos + len(part)))
            pos += len(part) + 1
    out: list[tuple[str, Decimal]] = []
    i = 0
    n = len(toks)

    def is_num(w: str, prev_conn: bool) -> bool:
        return w in _UNITS or w in _HUNDRED or w in _BIG or (prev_conn and w in ("un", "une"))

    while i < n:
        if not is_num(toks[i][0], False):
            i += 1
            continue
        start = toks[i][1]
        total = 0
        cur = 0
        j = i
        end = toks[i][2]
        while j < n:
            w = toks[j][0]
            prev_conn = j > i and toks[j - 1][0] in _CONNECTORS
            if w in _CONNECTORS:
                nxt = toks[j + 1][0] if j + 1 < n else ""
                if (
                    j > i
                    and (is_num(nxt, True))
                    and text[toks[j - 1][2] : toks[j][1]].strip(" \t-") == ""
                ):
                    j += 1
                    continue
                break
            if not is_num(w, prev_conn):
                break
            if w in ("un", "une"):
                cur += 1
            elif w in _UNITS:
                cur += _UNITS[w]
            elif w in _HUNDRED:
                cur = (cur or 1) * 100
            else:
                total += (cur or 1) * _BIG[w]
                cur = 0
            end = toks[j][2]
            j += 1
        out.append((text[start:end], Decimal(total + cur)))
        i = max(j, i + 1)
    return out


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


def _candidates(m: re.Match[str]) -> set[Decimal]:
    values = _to_decimals(m.group("num"))
    tail = (m.group("tail") or "").strip().lower()
    scale = _SCALES.get(tail)
    return {_canon(v * scale) if scale else _canon(v) for v in values}


def extract_numbers(text: str) -> list[set[Decimal]]:
    """One set of candidate values per digit number found in `text` (scaled when suffixed)."""
    found: list[set[Decimal]] = []
    for m in _NUM_RE.finditer(text):
        cands = _candidates(m)
        if cands:
            found.append(cands)
    return found


def number_values(text: str) -> set[Decimal]:
    """Every value any number of `text` can stand for (used to build the context's number set)."""
    out: set[Decimal] = set()
    for cands in extract_numbers(text):
        out |= cands
    for _, value in _word_numbers(text):
        out.add(_canon(value))
    return out


def strip_non_claims(answer: str) -> str:
    """Remove what is not a numeric claim: the [F3] reference markers and 1. / 2) list markers."""
    return _LIST_MARKER_RE.sub("\n", _REF_RE.sub(" ", answer))


def classify_numbers(
    answer: str, verified: set[Decimal], noted: set[Decimal] | None = None
) -> tuple[list[str], list[str]]:
    """(unverified, from_notes), as written, in order.

    `verified` holds the values of code-computed context items; `noted` those found only in
    untrusted notes / comments. A number in `verified` is fine; one only in `noted` is reported
    in the second list; anything else in the first."""
    noted = noted or set()
    text = strip_non_claims(answer)
    bad: list[str] = []
    from_notes: list[str] = []

    def judge(cands: set[Decimal], written: str) -> None:
        if not cands or cands & verified:
            return
        target = from_notes if cands & noted else bad
        if written not in target:
            target.append(written)

    for m in _NUM_RE.finditer(text):
        judge(_candidates(m), m.group(0).strip())
    for written, value in _word_numbers(text):
        judge({_canon(value)}, written.strip())
    return bad[:50], from_notes[:50]


def unverified_numbers(answer: str, context_values: set[Decimal]) -> list[str]:
    """The numbers of `answer` that match no number of the context, as written, in order."""
    return classify_numbers(answer, context_values)[0]
