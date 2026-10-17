"""Sales glossary: a small FR -> EN map applied to accent-folded text before theme discovery, so
that "prix", "tarif" and "price" land on the same term. Keys and values are folded (no accents).
Words absent from the glossary are left unchanged."""

from __future__ import annotations

import re
import unicodedata

SALES_GLOSSARY: dict[str, str] = {
    "prix": "price",
    "tarif": "price",
    "tarifs": "price",
    "tarification": "price",
    "cher": "expensive",
    "chers": "expensive",
    "chere": "expensive",
    "couteux": "expensive",
    "remise": "discount",
    "remises": "discount",
    "reduction": "discount",
    "budget": "budget",
    "budgets": "budget",
    "gel": "freeze",
    "gele": "freeze",
    "trimestre": "quarter",
    "trimestres": "quarter",
    "semestre": "half",
    "securite": "security",
    "hebergement": "hosting",
    "donnees": "data",
    "rgpd": "gdpr",
    "conformite": "compliance",
    "integration": "integration",
    "integrations": "integration",
    "connecteur": "connector",
    "connecteurs": "connector",
    "synchronisation": "sync",
    "concurrent": "competitor",
    "concurrents": "competitor",
    "offre": "offer",
    "offres": "offer",
    "contrat": "contract",
    "contrats": "contract",
    "delai": "timeline",
    "delais": "timeline",
    "juridique": "legal",
    "formation": "training",
    "decision": "decision",
}

_TOKEN = re.compile(r"[a-z0-9]+")


def fold(text: str) -> str:
    """Lower-case and strip accents."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)
    )


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(fold(text))


def apply_glossary(words: list[str]) -> list[str]:
    return [SALES_GLOSSARY.get(w, w) for w in words]
