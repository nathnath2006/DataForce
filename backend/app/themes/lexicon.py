"""Known sales themes: a catalog of FR+EN patterns matched on accent-folded, lower-cased
sentences, plus detection of recurring competitor names. Deterministic, no network.

Matching rules (documented choices):
- Patterns are word-bounded: "price" matches "price", "prices", "pricing" but not "priceless" or
  "pricey". Inflections are listed explicitly instead of using open prefixes.
- Patterns are plain alternations of literals (no nested quantifiers), compiled once.
- English "report" alone is not a timing cue (a "SOC 2 report" is not a delay); the French
  "report/reporter" and the English "postpone/delay" are. "calendar" counts only as a project
  calendar ("calendrier de lancement"), since a calendar is also a product feature.
- A sentence can match several themes; a chunk carries every theme matched by one of its sentences.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.domain.enums import ThemeKind
from app.themes.discover import N_EXCERPTS, name_tokens, sentences
from app.themes.glossary import fold

NAME_MIN_DOCS = 3
NAME_MIN_CUE_RATIO = 0.5
MAX_NAMES = 5
TIME_BUDGET_S = 20.0


@dataclass(frozen=True)
class KnownDef:
    id: str
    label: str
    kind: str
    description: str
    pattern: re.Pattern[str]


def _rx(src: str) -> re.Pattern[str]:
    return re.compile(src)


_PRICE = (
    r"\b(?:prix|prices?|priced|pricing|tarifs?|tarification|couts?|couteu\w+|costs?|costly"
    r"|chers?(?!\s+(?:monsieur|madame|client|collegue|ami))|cheres?|expensive|cheap(?:er)?"
    r"|remises?|discounts?|reductions?)\b"
    r"|\bbudgets?\b(?!\s+(?:gel|freeze|freezes))(?<!gel des budget)(?<!gel du budget)"
    r"(?<!gel des budgets)(?<!gel du budgets)(?<!gel de budget)(?<!gel de budgets)"
)
_COMPETITOR = (
    r"\b(?:concurren\w+|competitors?|competition|competitive|alternatives?|rivals?"
    r"|offres? similaires?|similar (?:offers?|products?|solutions?|tools?)"
    r"|versus|vs"
    r"|(?:other|another|autres?) (?:vendors?|editeurs?|fournisseurs?|providers?|vendeurs?))\b"
    r"|\b(?:compare a|compare au|compare aux|compared to|compared with)"
    r"(?!\s+(?:ce|ca|what|how|last|our|notre|nos|l|la|le|les|the|my|mon|ma)\b)"
)
_SECURITY = (
    r"\b(?:securite|security|secure|rgpd|gdpr|hebergement\w*|heberge\w*|hosting|hosted"
    r"|conformite|compliance|compliant|conformes?|soc ?2|iso ?27001"
    r"|donnees personnelles|personal data|dpo|rssi|ciso|chiffrement|encryption)\b"
)
_INTEGRATION = (
    r"\b(?:integrations?|integrer|integre\w*|integrate\w*|apis?|connecteurs?|connectors?"
    r"|synchronisations?|synchroniser|sync|salesforce|hubspot|crm|erp|webhooks?"
    r"|imports?|exports?|importer|exporter)\b"
)
_TIMING = (
    r"\bgel (?:des |du |de )?budget\w*|\bbudget (?:freeze|gel)\w*|\bpas avant\b|\bnot before\b"
    r"|\bprochain trimestre\b|\bnext (?:quarter|year|month)\b"
    r"|\b(?:postpone\w*|delay\w*|retard\w*|decale\w*|suspendu\w*|reportees?)\b"
    r"|\breport(?:e|er|ons|ez) (?:le|la|les|ce|cette|notre|ca|au|apres|a plus tard)\b"
    r"|\bcalendrier (?:de|du) (?:lancement|deploiement|mise|projet|livraison|migration)\b"
    r"|\btimeline\b|\bfin d'annee\b"
    r"|\bend of (?:the )?(?:year|quarter)\b|\bon hold\b|\bpushed back\b"
)
_LEGAL = (
    r"\b(?:contrats?|contracts?|juridique|legal|clauses?|dpa|conditions generales"
    r"|terms and conditions|terms of (?:service|use)|cgv|cgu)\b"
)
_ONBOARDING = (
    r"\b(?:formations?|training|onboarding|deploiement|rollout|roll-out|accompagnement"
    r"|mise en route|go-live)\b"
)
_SUPPORT = r"\b(?:support|sla|assistance|hotline|helpdesk|temps de reponse|response time)\b"

CATALOG: tuple[KnownDef, ...] = tuple(
    KnownDef(i, label, kind.value, desc, _rx(src))
    for i, label, kind, desc, src in (
        ("price", "Price", ThemeKind.OBJECTION, "Price, cost, discounts and budget.", _PRICE),
        (
            "competitor",
            "Competitors",
            ThemeKind.COMPETITOR,
            "Competing vendors and alternatives.",
            _COMPETITOR,
        ),
        (
            "security",
            "Security and compliance",
            ThemeKind.OBJECTION,
            "Security, GDPR, hosting and compliance.",
            _SECURITY,
        ),
        (
            "integration",
            "Integrations",
            ThemeKind.NEED,
            "Integrations, API, connectors and CRM sync.",
            _INTEGRATION,
        ),
        (
            "timing",
            "Timing",
            ThemeKind.TIMING,
            "Budget freezes, delays and calendar constraints.",
            _TIMING,
        ),
        ("legal", "Legal and contract", ThemeKind.OBJECTION, "Contract and legal terms.", _LEGAL),
        (
            "onboarding",
            "Onboarding and training",
            ThemeKind.NEED,
            "Training, rollout and onboarding.",
            _ONBOARDING,
        ),
        ("support", "Support", ThemeKind.NEED, "Support, SLA and response time.", _SUPPORT),
    )
)
BY_ID = {d.id: d for d in CATALOG}
BY_LABEL = {d.label: d for d in CATALOG}

# --- competitor names ----------------------------------------------------------------------------
_CAP = re.compile(r"\b[A-ZÀ-Ý][\wÀ-ÿ]{2,}\b")
_ANY_WORD = re.compile(r"[^\W\d_]{3,}")
_CUE = re.compile(
    r"\b(?:vs|versus|chez|than|compar\w*|prefer\w*|looking at|regard\w*|trial\w*|trialled"
    r"|test\w*|essay\w*|demo|demonstration|differenti\w*|mieux que|switch\w*|rival\w*"
    r"|competitor\w*|concurren\w*|alternative\w*)\b"
)
# Capitalised words that are never competitor names even in a competitor-like sentence.
_NOT_NAMES = frozenset(
    """salesforce hubspot google microsoft linkedin slack zoom teams excel outlook gmail notion
    europe france paris lundi mardi mercredi jeudi vendredi samedi dimanche monday tuesday
    wednesday thursday friday saturday sunday janvier fevrier mars avril mai juin juillet aout
    septembre octobre novembre decembre january february march april june july august september
    october november december""".split()
)


def _name_candidates(
    texts: Sequence[str], doc_ids: Sequence[object], bad: frozenset[str]
) -> list[str]:
    """Recurring capitalised words used like a competitor in at least NAME_MIN_DOCS meetings."""
    docs: dict[str, set[object]] = {}
    cue_docs: dict[str, set[object]] = {}
    shown: dict[str, str] = {}
    lower: set[str] = set()
    for ci, text in enumerate(texts):
        for sent in sentences(text):
            first = _ANY_WORD.search(sent)
            start = first.start() if first else 0
            for m in _ANY_WORD.finditer(sent):
                if not m.group(0)[0].isupper():
                    lower.add(fold(m.group(0)))
            for m in _CAP.finditer(sent):
                word = m.group(0)
                key = fold(word)
                if m.start() <= start or word[1:].isupper() or not word[1:].islower():
                    continue
                if key in bad or key in _NOT_NAMES:
                    continue
                shown.setdefault(key, word)
                docs.setdefault(key, set()).add(doc_ids[ci])
                if _CUE.search(fold(sent[max(0, m.start() - 30) : m.end() + 25])):
                    cue_docs.setdefault(key, set()).add(doc_ids[ci])
    ranked = [
        (-len(cue_docs[k]), k)
        for k in docs
        if k in cue_docs
        and k not in lower
        and len(cue_docs[k]) >= NAME_MIN_DOCS
        and len(cue_docs[k]) / len(docs[k]) >= NAME_MIN_CUE_RATIO
    ]
    ranked.sort()
    return [shown[k] for _, k in ranked[:MAX_NAMES]]


# --- matching ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class KnownFound:
    id: str
    label: str
    kind: str
    description: str
    top_terms: list[str]
    members: list[tuple[int, float]]  # (input index, weight in 0.1..1)
    excerpts: list[tuple[int, str]]  # (input index, exact sentence)
    n_documents: int


@dataclass(frozen=True)
class KnownMatch:
    found: list[KnownFound]
    matched: frozenset[tuple[int, int]]  # (chunk index, sentence index) matching any known theme
    competitor_names: list[str] = field(default_factory=list)


def _hits(rx: re.Pattern[str], folded: str) -> list[str]:
    return [m.group(0) for m in rx.finditer(folded)]


def match_known(
    texts: Sequence[str],
    names: Sequence[str] = (),
    doc_ids: Sequence[object] | None = None,
    *,
    max_chunks: int = 20_000,
) -> KnownMatch:
    """Known themes present in `texts`; themes with no hit are absent."""
    docs = list(doc_ids) if doc_ids is not None else list(range(len(texts)))
    texts = list(texts)[:max_chunks]
    t0 = time.monotonic()
    comp_names = _name_candidates(texts, docs, name_tokens(names))
    name_rx = (
        re.compile(r"\b(?:" + "|".join(re.escape(fold(n)) for n in comp_names) + r")\b")
        if comp_names
        else None
    )
    per: dict[str, list[tuple[int, int, str, int, list[str]]]] = {d.id: [] for d in CATALOG}
    matched: set[tuple[int, int]] = set()
    for ci, text in enumerate(texts):
        if time.monotonic() - t0 > TIME_BUDGET_S:
            break
        for si, sent in enumerate(sentences(text)):
            folded = fold(sent)
            for d in CATALOG:
                hits = _hits(d.pattern, folded)
                if d.id == "competitor" and name_rx is not None:
                    hits += _hits(name_rx, folded)
                if hits:
                    matched.add((ci, si))
                    per[d.id].append((ci, si, sent, len(hits), hits))
    found = []
    for d in CATALOG:
        rows = per[d.id]
        if not rows:
            continue
        best: dict[int, int] = {}
        terms: Counter[str] = Counter()
        for ci, _, _, n, hits in rows:
            best[ci] = max(best.get(ci, 0), n)
            terms.update(hits)
        members = [(ci, max(0.1, min(1.0, n / 10))) for ci, n in sorted(best.items())]
        top = [t for t, _ in sorted(terms.items(), key=lambda kv: (-kv[1], kv[0]))[:10]]
        desc = d.description
        if d.id == "competitor" and comp_names:
            desc += " Names detected: " + ", ".join(comp_names) + "."
        found.append(
            KnownFound(
                d.id,
                d.label,
                d.kind,
                desc,
                top,
                members,
                _pick(rows, docs),
                len({docs[ci] for ci, _ in members}),
            )
        )
    found.sort(key=lambda f: (-f.n_documents, f.id))
    return KnownMatch(found, frozenset(matched), comp_names)


def _pick(rows: list[tuple[int, int, str, int, list[str]]], docs: Sequence[object]):
    """Up to N_EXCERPTS distinct sentences, most hits first, from distinct documents if possible."""
    chosen: list[tuple[int, str]] = []
    rest: list[tuple[int, str]] = []
    seen_text: set[str] = set()
    seen_doc: set[object] = set()
    for ci, _si, sent, _, _ in sorted(rows, key=lambda r: (-r[3], r[0], r[1])):
        if sent in seen_text:
            continue
        seen_text.add(sent)
        if docs[ci] in seen_doc:
            rest.append((ci, sent))
            continue
        seen_doc.add(docs[ci])
        chosen.append((ci, sent))
        if len(chosen) == N_EXCERPTS:
            return chosen
    return (chosen + rest)[:N_EXCERPTS]


def best_known_sentence(label: str, text: str, extra_terms: Sequence[str] = ()) -> str:
    """The sentence of `text` with the most hits for the known theme `label` (first on ties)."""
    d = BY_LABEL.get(label)
    best: tuple[int, str] | None = None
    for s in sentences(text):
        folded = fold(s)
        n = len(_hits(d.pattern, folded)) if d else 0
        n += sum(folded.count(fold(t)) for t in extra_terms)
        if best is None or n > best[0]:
            best = (n, s)
    return best[1] if best else text.strip()
