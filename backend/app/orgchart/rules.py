"""Rule-based manager proposals (contract M2b §4). Pure functions over plain records: no DB.

Per account, over the contacts that have no manager link and a known function and seniority:
R0 finds the root (exactly one executive c_level), R1 sends the other c_level contacts to it,
R2 proposes the nearest level above in the same function (several -> ambiguous), R3 sends a
senior contact (>= head) with nobody above in their function to the root.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass

RANKS: dict[str, int] = {"individual": 0, "manager": 1, "head": 2, "vp": 3, "c_level": 4}
_UNKNOWN = {"unknown", "", None}

R1 = "c_level_to_ceo"
R2 = "next_level_in_function"
R3 = "senior_to_ceo"


@dataclass(frozen=True)
class Person:
    id: uuid.UUID
    account_id: uuid.UUID
    title: str | None
    function: str | None
    seniority: str | None
    manager_id: uuid.UUID | None = None  # the current link (manual or accepted)

    @property
    def rank(self) -> int | None:
        return RANKS.get(self.seniority or "")

    @property
    def known(self) -> bool:
        return self.function not in _UNKNOWN and self.rank is not None


@dataclass(frozen=True)
class RuleProposal:
    contact_id: uuid.UUID
    manager_id: uuid.UUID | None  # None when ambiguous
    candidates: tuple[uuid.UUID, ...]  # the candidates when ambiguous, else empty
    rule: str
    evidence: dict[str, str | None]

    @property
    def ambiguous(self) -> bool:
        return self.manager_id is None


def would_cycle(
    parents: dict[uuid.UUID, uuid.UUID | None], contact: uuid.UUID, manager: uuid.UUID
) -> bool:
    """True when making `manager` the boss of `contact` closes a loop in `parents`."""
    current: uuid.UUID | None = manager
    seen: set[uuid.UUID] = set()
    while current is not None and current not in seen:
        if current == contact:
            return True
        seen.add(current)
        current = parents.get(current)
    return False


def find_root(people: Iterable[Person]) -> Person | None:
    """R0: the only executive c_level contact of the account, else None."""
    roots = [p for p in people if p.function == "executive" and p.seniority == "c_level"]
    return roots[0] if len(roots) == 1 else None


def _evidence(contact: Person, manager: Person, explanation: str) -> dict[str, str | None]:
    return {
        "contact_title": contact.title,
        "manager_title": manager.title,
        "contact_class": f"{contact.function}/{contact.seniority}",
        "manager_class": f"{manager.function}/{manager.seniority}",
        "explanation": explanation,
    }


def propose_for_account(
    people: Collection[Person],
    rejected: Collection[tuple[uuid.UUID, uuid.UUID]] = (),
) -> list[RuleProposal]:
    """Proposals for one account. `rejected` holds (contact, manager) pairs never to re-propose.
    People of another account are ignored (never a cross-account proposal)."""
    if not people:
        return []
    account_id = next(iter(people)).account_id
    mine = [p for p in people if p.account_id == account_id]
    by_id = {p.id: p for p in mine}
    parents = {p.id: p.manager_id for p in mine}
    known = [p for p in mine if p.known]
    root = find_root(known)
    rejected_set = set(rejected)

    def allowed(contact: Person, manager: Person) -> bool:
        return (
            manager.id != contact.id
            and manager.id in by_id
            and (contact.id, manager.id) not in rejected_set
            and not would_cycle(parents, contact.id, manager.id)
        )

    out: list[RuleProposal] = []
    for p in sorted(known, key=lambda x: str(x.id)):
        if p.manager_id is not None or (root is not None and p.id == root.id):
            continue
        rank = p.rank
        assert rank is not None
        if root is not None and p.seniority == "c_level":  # R1
            if allowed(p, root):
                out.append(
                    RuleProposal(
                        p.id,
                        root.id,
                        (),
                        R1,
                        _evidence(
                            p, root, "C-level contact reports to the account's top executive"
                        ),
                    )
                )
            continue
        above = [q for q in known if q.function == p.function and (q.rank or 0) > rank]
        if above:  # R2
            nearest = min(q.rank for q in above if q.rank is not None)
            cands = [q for q in above if q.rank == nearest and allowed(p, q)]
            cands.sort(key=lambda q: str(q.id))
            if len(cands) == 1:
                out.append(
                    RuleProposal(
                        p.id,
                        cands[0].id,
                        (),
                        R2,
                        _evidence(
                            p,
                            cands[0],
                            f"Next level above in the {p.function} function",
                        ),
                    )
                )
            elif len(cands) > 1:
                first = cands[0]
                ev = _evidence(
                    p, first, f"Several people at the next level in the {p.function} function"
                )
                ev["manager_title"] = None
                ev["manager_class"] = f"{first.function}/{first.seniority}"
                out.append(RuleProposal(p.id, None, tuple(q.id for q in cands), R2, ev))
            continue
        if rank >= RANKS["head"] and root is not None and allowed(p, root):  # R3
            out.append(
                RuleProposal(
                    p.id,
                    root.id,
                    (),
                    R3,
                    _evidence(
                        p,
                        root,
                        f"Senior {p.function} contact with nobody above in the function "
                        "reports to the account's top executive",
                    ),
                )
            )
    return out
