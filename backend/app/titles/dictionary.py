"""FR/EN keyword dictionary: normalised title -> (function, seniority).

Every rule is a phrase of words (stopwords removed, plural / feminine folded by `canon`). Matching
is "longest phrase first, and a phrase consumes its words": "chief executive officer" is executive
/ c_level and does not also match "executive" (individual); "vice president" is not "president".
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import JobFunction as F
from app.domain.enums import Seniority as S

STOPWORDS = frozenset(
    "de des du la le les d l et and of the for en a au aux pour in at".split()
)  # fmt: skip

# Feminine / variant spellings folded to one canonical word (after accent stripping).
ALIASES: dict[str, str] = {
    "directrice": "directeur", "directrices": "directeur", "directeurs": "directeur",
    "chargee": "charge", "chargees": "charge", "charges": "charge",
    "fondatrice": "fondateur", "fondateurs": "fondateur",
    "presidente": "president", "gerante": "gerant", "commerciale": "commercial",
    "commerciaux": "commercial", "commerciales": "commercial",
    "financiere": "financier", "financieres": "financier", "financiers": "financier",
    "developpeuse": "developpeur", "assistante": "assistant", "ingenieure": "ingenieur",
    "cheffe": "chef", "consultante": "consultant", "specialiste": "specialist",
    "manageuse": "manager", "techniques": "technique", "humaines": "humaine",
    "analyste": "analyst", "stagiaires": "stagiaire", "ventes": "vente", "grands": "grand",
    "comptes": "compte", "affaires": "affaires", "responsables": "responsable",
    "comptables": "comptable", "juniors": "junior", "seniors": "senior",
}  # fmt: skip

ABBREVIATIONS: dict[str, str] = {
    "dir": "directeur",
    "resp": "responsable",
    "dg": "directeur general",
    "pdg": "president directeur general",
    "daf": "directeur administratif et financier",
    "dsi": "directeur systemes information",
    "vp": "vice president",
    "svp": "senior vice president",
    "sdr": "sales development representative",
    "bdr": "business development representative",
    "ae": "account executive",
    "kam": "key account manager",
}


def canon(token: str) -> str:
    if token in ALIASES:
        return ALIASES[token]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


@dataclass(frozen=True)
class Rule:
    words: tuple[str, ...]
    function: F | None
    seniority: S | None


_RAW: list[tuple[str, F | None, S | None]] = [
    # --- executive
    ("chief executive officer", F.EXECUTIVE, S.C_LEVEL),
    ("ceo", F.EXECUTIVE, S.C_LEVEL),
    ("president directeur general", F.EXECUTIVE, S.C_LEVEL),
    ("directeur general", F.EXECUTIVE, S.C_LEVEL),
    ("general manager", F.EXECUTIVE, S.C_LEVEL),
    ("president", F.EXECUTIVE, S.C_LEVEL),
    ("founder", F.EXECUTIVE, S.C_LEVEL),
    ("co founder", F.EXECUTIVE, S.C_LEVEL),
    ("fondateur", F.EXECUTIVE, S.C_LEVEL),
    ("managing director", F.EXECUTIVE, S.C_LEVEL),
    ("gerant", F.EXECUTIVE, S.C_LEVEL),
    # --- sales
    ("commercial", F.SALES, None),
    ("vente", F.SALES, None),
    ("sales", F.SALES, None),
    ("business developer", F.SALES, S.INDIVIDUAL),
    ("business development", F.SALES, None),
    ("business development representative", F.SALES, S.INDIVIDUAL),
    ("sales development representative", F.SALES, S.INDIVIDUAL),
    ("sales development rep", F.SALES, S.INDIVIDUAL),
    ("account executive", F.SALES, S.INDIVIDUAL),
    # "manager" inside an account-manager title is a job name, not a management level
    ("account manager", F.SALES, S.INDIVIDUAL),
    ("key account manager", F.SALES, S.INDIVIDUAL),
    ("chief revenue officer", F.SALES, S.C_LEVEL),
    ("chief commercial officer", F.SALES, S.C_LEVEL),
    ("chief customer officer", F.SALES, S.C_LEVEL),
    ("cro", F.SALES, S.C_LEVEL),
    ("cco", F.SALES, S.C_LEVEL),
    ("key account", F.SALES, None),
    ("ingenieur affaires", F.SALES, S.INDIVIDUAL),
    ("charge affaires", F.SALES, S.INDIVIDUAL),
    ("grand compte", F.SALES, None),
    # --- marketing
    ("marketing", F.MARKETING, None),
    ("cmo", F.MARKETING, S.C_LEVEL),
    ("chief marketing officer", F.MARKETING, S.C_LEVEL),
    ("community manager", F.MARKETING, S.INDIVIDUAL),
    ("communication", F.MARKETING, None),
    ("content", F.MARKETING, None),
    ("growth", F.MARKETING, None),
    ("brand", F.MARKETING, None),
    ("marque", F.MARKETING, None),
    # --- finance
    ("cfo", F.FINANCE, S.C_LEVEL),
    ("chief financial officer", F.FINANCE, S.C_LEVEL),
    ("treasury", F.FINANCE, None),
    ("treasurer", F.FINANCE, None),
    ("tresorier", F.FINANCE, None),
    ("directeur administratif financier", F.FINANCE, S.C_LEVEL),
    ("financier", F.FINANCE, None),
    ("finance", F.FINANCE, None),
    ("comptable", F.FINANCE, None),
    ("comptabilite", F.FINANCE, None),
    ("accounting", F.FINANCE, None),
    ("accountant", F.FINANCE, None),
    ("controle gestion", F.FINANCE, None),
    ("controleur gestion", F.FINANCE, None),
    ("tresorerie", F.FINANCE, None),
    # --- operations
    ("operation", F.OPERATIONS, None),
    ("ops", F.OPERATIONS, None),
    ("logistique", F.OPERATIONS, None),
    ("supply chain", F.OPERATIONS, None),
    ("coo", F.OPERATIONS, S.C_LEVEL),
    ("chief operating officer", F.OPERATIONS, S.C_LEVEL),
    ("purchasing", F.OPERATIONS, None),
    ("procurement", F.OPERATIONS, None),
    ("achat", F.OPERATIONS, None),
    ("acheteur", F.OPERATIONS, None),
    ("buyer", F.OPERATIONS, None),
    # --- tech
    ("cto", F.TECH, S.C_LEVEL),
    ("cio", F.TECH, S.C_LEVEL),
    ("chief technology officer", F.TECH, S.C_LEVEL),
    ("chief information officer", F.TECH, S.C_LEVEL),
    ("chief information security officer", F.TECH, S.C_LEVEL),
    ("chief data officer", F.TECH, S.C_LEVEL),
    ("chief product officer", F.TECH, S.C_LEVEL),
    # no product function in JobFunction: product titles map to tech (documented choice)
    ("product manager", F.TECH, S.INDIVIDUAL),
    ("product", F.TECH, None),
    ("produit", F.TECH, None),
    ("directeur systemes information", F.TECH, S.C_LEVEL),
    ("technique", F.TECH, None),
    ("technology", F.TECH, None),
    ("tech", F.TECH, None),
    ("it", F.TECH, None),
    ("engineering", F.TECH, None),
    ("ingenierie", F.TECH, None),
    ("developpeur", F.TECH, S.INDIVIDUAL),
    ("developer", F.TECH, S.INDIVIDUAL),
    ("software", F.TECH, None),
    ("devops", F.TECH, None),
    ("data", F.TECH, None),
    # --- hr
    ("rh", F.HR, None),
    ("ressource humaine", F.HR, None),
    ("human resource", F.HR, None),
    # "DRH" (acronym) is c_level; the spelled-out "Directeur des Ressources Humaines" is a head
    # (directeur -> head), like "HR Director". "Chief People Officer" is c_level.
    ("drh", F.HR, S.C_LEVEL),
    ("chief people officer", F.HR, S.C_LEVEL),
    ("chief human resource officer", F.HR, S.C_LEVEL),
    ("hr", F.HR, None),
    ("chro", F.HR, S.C_LEVEL),
    ("talent", F.HR, None),
    ("recrutement", F.HR, None),
    ("recruiter", F.HR, None),
    ("people", F.HR, None),
    # --- seniority only
    ("customer success manager", None, S.INDIVIDUAL),
    ("chief", None, S.C_LEVEL),
    ("cpo", F.TECH, S.C_LEVEL),
    ("cdo", None, S.C_LEVEL),
    ("cso", None, S.C_LEVEL),
    ("senior vice president", None, S.VP),
    ("vice president", None, S.VP),
    ("directeur", None, S.HEAD),
    ("director", None, S.HEAD),
    ("head", None, S.HEAD),
    ("manager", None, S.MANAGER),
    ("responsable", None, S.MANAGER),
    ("lead", None, S.MANAGER),
    ("chef", None, S.MANAGER),
    ("executive", None, S.INDIVIDUAL),
    ("ingenieur", None, S.INDIVIDUAL),
    ("charge", None, S.INDIVIDUAL),
    ("assistant", None, S.INDIVIDUAL),
    ("junior", None, S.INDIVIDUAL),
    ("representative", None, S.INDIVIDUAL),
    ("rep", None, S.INDIVIDUAL),
    ("consultant", None, S.INDIVIDUAL),
    ("specialist", None, S.INDIVIDUAL),
    ("analyst", None, S.INDIVIDUAL),
    ("stagiaire", None, S.INDIVIDUAL),
    ("intern", None, S.INDIVIDUAL),
    ("associate", None, S.INDIVIDUAL),
    ("technicien", None, S.INDIVIDUAL),
]  # fmt: skip

RULES: tuple[Rule, ...] = tuple(
    sorted(
        (Rule(tuple(canon(w) for w in p.split()), f, s) for p, f, s in _RAW),
        key=lambda r: -len(r.words),
    )
)


def vocabulary() -> frozenset[str]:
    """Every surface word the typo repair may map to."""
    words: set[str] = set(STOPWORDS) | set(ALIASES)
    for phrase, _, _ in _RAW:
        words.update(phrase.split())
    for expansion in ABBREVIATIONS.values():
        words.update(expansion.split())
    return frozenset(words)


SENIORITY_RANK = {S.C_LEVEL: 5, S.VP: 4, S.HEAD: 3, S.MANAGER: 2, S.INDIVIDUAL: 1}
