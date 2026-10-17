"""Pure title normaliser: case, accents, punctuation, abbreviations, typo repair."""

from __future__ import annotations

import difflib
import re
import unicodedata

from app.titles.dictionary import ABBREVIATIONS, vocabulary

_VOCAB = vocabulary()
_VOCAB_LIST = sorted(_VOCAB)
_SEPARATORS = re.compile(r"[.\-/&,;:()'’`_|+]")
_SPACES = re.compile(r"\s+")
FUZZY_MIN_LEN = 5
FUZZY_CUTOFF = 0.85


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _transposition_match(token: str) -> str | None:
    """A short token (3-4 letters) that is one adjacent swap away from exactly one vocabulary
    word of the same length: 'srd' -> 'sdr'. Ambiguous swaps are left alone."""
    found: set[str] = set()
    for i in range(len(token) - 1):
        swapped = token[:i] + token[i + 1] + token[i] + token[i + 2 :]
        if swapped != token and swapped in _VOCAB:
            found.add(swapped)
    return found.pop() if len(found) == 1 else None


def _repair_token(token: str) -> str:
    if token in _VOCAB or token.isdigit():
        return token
    if len(token) >= FUZZY_MIN_LEN:
        close = difflib.get_close_matches(token, _VOCAB_LIST, n=1, cutoff=FUZZY_CUTOFF)
        return close[0] if close else token
    if len(token) >= 3:
        return _transposition_match(token) or token
    return token


def _split_glued(glued: str) -> list[str] | None:
    """'accountexecutive' -> ['account', 'executive'] when both halves are vocabulary words."""
    if glued in _VOCAB:
        return [glued]
    for i in range(3, len(glued) - 2):
        left, right = glued[:i], glued[i:]
        if left in _VOCAB and right in _VOCAB:
            return [left, right]
    return None


def _repair(tokens: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if i + 1 < len(tokens) and (tok not in _VOCAB or tokens[i + 1] not in _VOCAB):
            # a stray space may split a word: retry the pair glued
            nxt = tokens[i + 1]
            parts = _split_glued(tok + nxt)
            if parts is not None and (tok not in _VOCAB or nxt not in _VOCAB):
                out.extend(parts)
                i += 2
                continue
        out.append(_repair_token(tok))
        i += 1
    return out


def normalize_title(title: str | None) -> str:
    """Lowercase, no accents, punctuation -> spaces, abbreviations expanded, typos repaired.
    Returns "" for a missing or blank title."""
    if not title:
        return ""
    text = _strip_accents(title).lower()
    text = _SEPARATORS.sub(" ", text)
    tokens = _SPACES.sub(" ", text).strip().split(" ")
    expanded: list[str] = []
    for tok in tokens:
        if not tok:
            continue
        expanded.extend(ABBREVIATIONS.get(tok, tok).split())
    repaired = _repair(expanded)
    final: list[str] = []
    for tok in repaired:  # a typo may itself have been an abbreviation: expand once more
        final.extend(ABBREVIATIONS.get(tok, tok).split())
    return " ".join(final)
