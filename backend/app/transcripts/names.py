"""Match a speaker name to a contact or a user. Pure.

Order-insensitive, accent- and case-insensitive. A match must be unique: an ambiguous name
("Marie") that fits two people matches nobody.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

_TOKEN = re.compile(r"[^\W\d_]+")


def name_tokens(name: str) -> tuple[str, ...]:
    folded = "".join(
        c for c in unicodedata.normalize("NFKD", name.lower()) if not unicodedata.combining(c)
    )
    return tuple(_TOKEN.findall(folded))


@dataclass(frozen=True)
class Candidate:
    id: uuid.UUID
    name: str


@dataclass(frozen=True)
class Match:
    kind: str  # "contact" | "user"
    id: uuid.UUID


def _fits(speaker: tuple[str, ...], person: tuple[str, ...]) -> bool:
    """Every speaker token is a person token, or an initial of one (each person token used once)."""
    pool = list(person)
    for tok in speaker:
        for i, cand in enumerate(pool):
            if cand == tok or (len(tok) == 1 and cand.startswith(tok)):
                del pool[i]
                break
        else:
            return False
    return True


def match_speaker(
    speaker: str | None, contacts: Sequence[Candidate], users: Sequence[Candidate]
) -> Match | None:
    """Exact (same tokens) matches first, then partial ones (first name, initials). Contacts and
    users compete: more than one hit at a tier means no match."""
    if not speaker:
        return None
    tokens = name_tokens(speaker)
    if not tokens:
        return None
    people = [("contact", c.id, name_tokens(c.name)) for c in contacts] + [
        ("user", u.id, name_tokens(u.name)) for u in users
    ]
    exact = [(k, i) for k, i, t in people if t and sorted(t) == sorted(tokens)]
    if len(exact) == 1:
        return Match(*exact[0])
    if exact:
        return None
    partial = [(k, i) for k, i, t in people if t and _fits(tokens, t)]
    return Match(*partial[0]) if len(partial) == 1 else None
