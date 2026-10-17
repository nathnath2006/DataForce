"""Deterministic FR/EN extraction of org-chart statements from meeting chunks (contract §4).

Pure: no DB. Regular expressions run over an accent- and case-folded copy of each chunk (same
length as the original, so offsets carry over). `{NAME}` is an alternation of the aliases of the
account's contacts, so a name that does not resolve to exactly one contact never matches.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class ContactRef:
    id: uuid.UUID
    full_name: str


@dataclass(frozen=True)
class ChunkRec:
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    speaker: str | None
    contact_id: uuid.UUID | None
    char_start: int
    char_end: int
    text: str


@dataclass(frozen=True)
class Finding:
    kind: str  # reports_to | champion | blocker | decision_maker
    contact_id: uuid.UUID  # who the statement is about (the subordinate / the signalled person)
    manager_id: uuid.UUID | None
    pattern: str
    evidence: dict[str, object]


def fold(text: str) -> str:
    """Lowercase, accent-free, apostrophes straightened; always the same length as `text`."""
    out: list[str] = []
    for ch in text:
        if ch in "’‘ʼ`´":
            out.append("'")
            continue
        base = unicodedata.normalize("NFD", ch)[0].lower()
        out.append(base if len(base) == 1 else ch.lower()[:1] or ch)
    return "".join(out)


def aliases(contacts: Sequence[ContactRef]) -> dict[str, uuid.UUID]:
    """Folded alias -> contact id, only for aliases that point at one contact: the full name,
    first + last name, and the first name when no other contact shares it."""
    seen: dict[str, set[uuid.UUID]] = {}
    for c in contacts:
        tokens = fold(c.full_name).split()
        if not tokens:
            continue
        names = {" ".join(tokens)}
        if len(tokens) >= 2:
            names.add(f"{tokens[0]} {tokens[-1]}")
        names.add(tokens[0])
        for name in names:
            if len(name) >= 2:
                seen.setdefault(name, set()).add(c.id)
    return {a: next(iter(ids)) for a, ids in seen.items() if len(ids) == 1}


_S = r"\s+"

# (id, kind, subject, regex source with {N} for the name). subject: "speaker" = first person,
# "name" = the person named, "name_manager" = speaker/name pairs for reports_to.
_PATTERNS: list[tuple[str, str, str, str]] = [
    # reports_to, subject is the speaker unless noted
    ("en_i_report_to", "reports_to", "speaker", rf"\bi{_S}report{_S}to{_S}{{N}}"),
    (
        "en_my_boss_is",
        "reports_to",
        "speaker",
        rf"\bmy{_S}(?:boss|manager|line{_S}manager){_S}is{_S}{{N}}",
    ),
    (
        "en_is_my_boss",
        "reports_to",
        "speaker",
        rf"{{N}}{_S}is{_S}my{_S}(?:line{_S})?(?:boss|manager)\b",
    ),
    ("fr_je_reporte_a", "reports_to", "speaker", rf"\bje{_S}reporte{_S}a{_S}{{N}}"),
    (
        "fr_mon_manager_est",
        "reports_to",
        "speaker",
        rf"\bmon{_S}(?:manager|n\+1|responsable|chef){_S}(?:c'est|est){_S}{{N}}",
    ),
    (
        "fr_est_mon_manager",
        "reports_to",
        "speaker",
        rf"{{N}}{_S}est{_S}mon{_S}(?:manager|n\+1|chef|responsable)\b",
    ),
    (
        "fr_sous_la_responsabilite",
        "reports_to",
        "speaker",
        rf"\bje{_S}suis{_S}sous{_S}la{_S}responsabilite{_S}de{_S}{{N}}",
    ),
    # champion (first person)
    (
        "en_ill_champion",
        "champion",
        "speaker",
        rf"\bi(?:'ll|{_S}will){_S}(?:push|champion|sponsor){_S}(?:this|it)\b",
    ),
    (
        "fr_je_vais_pousser",
        "champion",
        "speaker",
        rf"\bje{_S}vais{_S}(?:pousser|porter|defendre){_S}(?:le{_S}dossier|le{_S}projet|ca)\b",
    ),
    # blocker (about NAME)
    (
        "en_is_against",
        "blocker",
        "name",
        rf"{{N}}{_S}is{_S}(?:against|not{_S}convinced|blocking)\b",
    ),
    (
        "fr_bloque",
        "blocker",
        "name",
        rf"{{N}}{_S}(?:bloque|est{_S}contre|n'est{_S}pas{_S}convaincu(?:e)?)\b",
    ),
    # decision maker
    (
        "en_makes_the_call",
        "decision_maker",
        "name",
        rf"{{N}}{_S}(?:makes|will{_S}make|has){_S}the{_S}(?:final{_S})?(?:decision|call)\b",
    ),
    (
        "fr_cest_qui_decide",
        "decision_maker",
        "name",
        rf"\bc'est{_S}{{N}}{_S}qui{_S}(?:decide|valide|signe|tranche)\b",
    ),
]

PATTERN_IDS = tuple(p[0] for p in _PATTERNS)


@lru_cache(maxsize=256)
def _compile(src: str, names_key: tuple[str, ...]) -> re.Pattern[str]:
    alt = "|".join(re.escape(n).replace(r"\ ", r"\s+") for n in names_key)
    body = src.replace("{N}", rf"(?<!\w)(?P<name>{alt})(?!\w)")
    return re.compile(body)


_BOUNDARY = ".!?\n"


def _sentence_span(text: str, start: int, end: int) -> tuple[int, int]:
    s = start
    while s > 0 and text[s - 1] not in _BOUNDARY:
        s -= 1
    e = end
    while e < len(text) and text[e] not in _BOUNDARY:
        e += 1
    if e < len(text) and text[e] != "\n":
        e += 1  # keep the closing punctuation
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def extract(
    chunks: Iterable[ChunkRec],
    contacts: Sequence[ContactRef],
    document_texts: dict[uuid.UUID, str],
) -> list[Finding]:
    """Findings from the chunks whose speaker matched one of `contacts`. The evidence excerpt is
    an exact substring of the document text at [char_start:char_end] (verified; dropped if not)."""
    if not contacts:
        return []
    alias = aliases(contacts)
    if not alias:
        return []
    names_key = tuple(sorted(alias, key=lambda a: (-len(a), a)))
    ids = {c.id for c in contacts}
    found: list[Finding] = []
    for chunk in sorted(chunks, key=lambda c: (str(c.document_id), c.char_start)):
        if chunk.contact_id is None or chunk.contact_id not in ids:
            continue
        doc_text = document_texts.get(chunk.document_id)
        if doc_text is None:
            continue
        folded = fold(chunk.text)
        for pid, kind, subject, src in _PATTERNS:
            if "{N}" not in src and subject == "name":
                continue
            rx = _compile(src, names_key) if "{N}" in src else _compile_plain(src)
            for m in rx.finditer(folded):
                named = alias.get(re.sub(r"\s+", " ", m.group("name"))) if "{N}" in src else None
                if "{N}" in src and named is None:
                    continue
                if kind == "reports_to":
                    if named == chunk.contact_id:
                        continue
                    contact_id, manager_id = chunk.contact_id, named
                elif subject == "speaker":
                    contact_id, manager_id = chunk.contact_id, None
                else:
                    assert named is not None
                    contact_id, manager_id = named, None
                s, e = _sentence_span(chunk.text, m.start(), m.end())
                start, end = chunk.char_start + s, chunk.char_start + e
                excerpt = chunk.text[s:e]
                if not excerpt or doc_text[start:end] != excerpt:
                    continue
                found.append(
                    Finding(
                        kind,
                        contact_id,
                        manager_id,
                        pid,
                        {
                            "document_id": str(chunk.document_id),
                            "chunk_id": str(chunk.chunk_id),
                            "excerpt": excerpt,
                            "speaker": chunk.speaker,
                            "char_start": start,
                            "char_end": end,
                            "pattern": pid,
                        },
                    )
                )
    return found


@lru_cache(maxsize=64)
def _compile_plain(src: str) -> re.Pattern[str]:
    return re.compile(src)
