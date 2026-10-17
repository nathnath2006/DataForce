"""Match a speaker name to a contact or a user. Pure.

Order-insensitive, accent- and case-insensitive. A match must be unique: an ambiguous name
("Marie") that fits two people matches nobody. With 2+ tokens the last name must match.
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
    """A partial match of a label with 2+ tokens: the person's LAST name must appear in full; every
    other label token is a person token or the initial of one (each person token used once).
    Initials alone never match (SR12-04/05): "Marie Curie" is not "Marie Dupont"."""
    if not person or person[-1] not in speaker:
        return False
    pool = list(person[:-1])
    rest = list(speaker)
    rest.remove(person[-1])
    for tok in rest:
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
    """Exact (same tokens) matches first, then partial ones. With 2+ tokens the last name must
    match; a single-token label (2+ letters) may match a first name only when it is unique among
    the account's contacts and the workspace users. Contacts and users compete: more than one hit
    at a tier means no match."""
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
    if len(tokens) == 1:
        if len(tokens[0]) < 2:
            return None
        partial = [(k, i) for k, i, t in people if len(t) > 1 and t[0] == tokens[0]]
    else:
        partial = [(k, i) for k, i, t in people if t and _fits(tokens, t)]
    return Match(*partial[0]) if len(partial) == 1 else None
