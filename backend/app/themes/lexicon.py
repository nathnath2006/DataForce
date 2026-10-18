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
    mask: re.Pattern[str] | None = None  # spans blanked out before matching


def _rx(src: str) -> re.Pattern[str]:
    return re.compile(src)


_PRICE = (
    r"\b(?:prix|prices?|priced|pricing|tarifs?|tarification|couts?(?!\s+de\s+la\s+vie)|couteu\w+"
    r"|costs?(?!-)(?!\s+of\s+living)|costly"
    r"|chers?(?!\s+(?:monsieur|madame|client|collegue|ami))|cheres?|expensive(?!-)|cheap(?:er)?"
    r"|remises?|discounts?|reductions?)\b"
    r"|\bbudgets?\b(?!\s+(?:gel|freeze|freezes|meeting|photo|vacances))"
    r"(?<!gel des budget)(?<!gel du budget)"
    r"(?<!gel des budgets)(?<!gel du budgets)(?<!gel de budget)(?<!gel de budgets)"
)
# The budget of an internal event is not about our price.
_PRICE_MASK = (
    r"\bbudgets? (?:de la |de l'|de |du |des |d'|for |of )(?:(?:the|our|my|this|la|le|les|l'"
    r"|notre|cette|ce|un|une|a|an) ?)?"
    r"(?:(?:internal|interne|annual|annuel|company|team|end-of-year|yearly) )*"
    r"(?:evenements?|seminaires?|offsites?|off-sites?|events?|part(?:y|ies)|soirees?|fetes?"
    r"|team-?building"
    r"|afterworks?|retreats?|conferences?|voyages?|noel|christmas|holiday|vacances?)\b"
)
# Competitor: "versus last year" compares time periods, not vendors.
_COMPETITOR_MASK = (
    r"\b(?:versus|vs\.?) (?:the )?(?:last|previous|prior|same|this|next|q[1-4]|\d{4}"
    r"|(?:l'|la |le )?(?:annee|an|mois|trimestre|semaine)|(?:janvier|fevrier|mars|avril|mai|juin"
    r"|juillet|aout"
    r"|septembre|octobre|novembre|decembre|january|february|march|april|june|july|august|september"
    r"|october|november|december)|year|quarter|month|week)\b"
)
_COMPETITOR = (
    r"\b(?:concurren\w+|competitors?|competition(?!\s+(?:en|de)\s+(?:athletisme|natation|sport"
    r"|ski))"
    r"|competitive(?!\s+(?:football|soccer|sports?|swimming|league|running|athletics))"
    r"|alternatives?|rivals?"
    r"|offres? similaires?|similar (?:offers?|products?|solutions?|tools?)"
    r"|versus|vs"
    r"|(?:other|another|autres?) (?:vendors?|editeurs?|fournisseurs?|providers?|vendeurs?)"
    r"|(?:autre|another) (?:solutions?|outils?|plateformes?|options?|tools?|platforms?)"
    r"|incumbents?|short-?list\w*|appels? d'offres?|rfps?"
    r"|(?:leur|their) (?:solution|outil|plateforme|logiciel|software|tool|platform)"
    r"|(?:current|existing|actuel\w*|existant\w*) (?:solution|tool|vendor|provider|supplier"
    r"|platform"
    r"|outil|fournisseur|prestataire|plateforme)s?"
    r"|(?:solution|outil|fournisseur|prestataire|plateforme)s? (?:actuel\w*|existant\w*)"
    r"|utilis(?:e|ons|ez|ent|ais|ions) (?:deja|actuellement|aujourd'hui|encore)"
    r"|(?:currently|already|still|presently) (?:use|using|run|running|rely on|working with)"
    r"|switch\w* (?:from|to|over|away)|migr\w+ (?:depuis|vers|from)|changer de (?:solution"
    r"|fournisseur|outil|prestataire)"
    r"|(?:looking at|evaluating|comparing|considering|testing|trialling|trialing) (?:other"
    r"|another|a few|several|two|three|some|different|multiple|competing|alternative|similar)"
    r"|(?:regardons|evaluons|comparons|testons|envisageons) (?:d'autres|plusieurs|quelques|deux"
    r"|trois|aussi))\b"
    r"|\b(?:compare a|compare au|compare aux|compared to|compared with)"
    r"(?!\s+(?:ce|ca|what|how|last|our|notre|nos|l|la|le|les|the|my|mon|ma)\b)"
)
_SECURITY = (
    r"\b(?:securite(?!\s+(?:routiere|sociale|de\s+l'emploi))|security|secure|rgpd|gdpr"
    r"|hebergement\w*|heberge\w*|hosting|hosted"
    r"|conformite|compliance|compliant|conformes?|soc ?2|iso ?27001"
    r"|donnees personnelles|personal data|dpo|rssi|ciso|chiffrement|encryption)\b"
)
_INTEGRATION = (
    r"\b(?:integrations?(?!\s+(?:d'|de\s+|des\s+)(?:nouveau\w*|stagiaires?|collaborat\w+|salaries?"
    r"|employes?|recrues?|apprentis?|alternants?|equipes?|personnel)"
    r"|\s+of\s+(?:new\s+(?:hires?|employees?|staff|joiners?|team\s+members?|recruits?)"
    r"|(?:the\s+)?(?:two|both|three)\b))|integrer|integre\w*|integrate\w*|apis?|connecteurs?"
    r"|connectors?"
    r"|synchronisations?|synchroniser|sync|salesforce|hubspot|crm|erp|webhooks?"
    r"|importer|exporter"
    r"|(?:imports?|exports?) (?:csv|excel|xlsx?|json|xml|api|automati\w+|en masse|massifs?|bulk"
    r"|de donnees|des donnees|de fichiers|of data|data|vers|to|from|depuis)"
    r"|(?:csv|excel|bulk|automati\w+) (?:import|export)s?|import/export)\b"
)
_TIMING = (
    r"\bgel (?:des |du |de )?budget\w*|\bbudget (?:freeze|gel)\w*|\bpas avant\b|\bnot before\b"
    r"|\bprochain trimestre\b|\bnext (?:quarter|year|month)\b"
    r"|\b(?:postpone\w*|delay\w*(?!\s+on\s+the\s+(?:train|bus|flight|metro))|retard\w*|decale\w*"
    r"|suspendu\w*|reportees?)\b"
    r"|\breport(?:e|er|ons|ez) (?:le|la|les|ce|cette|notre|ca|au|apres|a plus tard)\b"
    r"|\bcalendrier (?:de|du) (?:lancement|deploiement|mise|projet|livraison|migration)\b"
    r"|\btimeline\b(?!\s+(?:linkedin|facebook|instagram|twitter))|\bfin d'annee\b"
    r"|\bend of (?:the )?(?:year|quarter)\b|\bon hold\b|\bpushed back\b"
    r"|\bq[1-4]\b|\bfin (?:de|du) (?:trimestre|semestre|exercice)\b|\bnot (?:until|now"
    r"|this (?:quarter|year))\b"
    r"|\bpas (?:cette annee|ce trimestre|maintenant|pour l'instant|tout de suite|dans l'immediat)\b"
    r"|\b(?:annee|an|trimestre|semestre|exercice) prochain\b|\bnext (?:fiscal|half|semester)\b"
    r"|\bapres l'ete\b|\bafter (?:the )?(?:summer|holidays?)\b"
    r"|\bnot (?:a|our) priority\b|\bpas (?:une|la) priorite\b|\bplus tard\b"
)
# Lateness to a meeting is not a timing objection; neither is a busy remark about quarter end.
_TIMING_MASK = (
    r"\b(?:minutes?|heures?|hours?) (?:de |of )?(?:retard|late)\b"
    r"|\b(?:je|j'|tu|il|elle|ils|elles)\s*(?:\w+ ){0,3}?en retard\b"
    r"|\bretard sur (?:mon|ma|mes|son|ses) (?:agenda|calendrier|planning|emploi du temps)\b"
    r"|\ben retard (?:pour|a) (?:la |le |l'|cette |notre )?(?:reunion|call|appel|rdv|rendez-vous"
    r"|visio|meeting|point|demo)\b"
    r"|\bend of (?:the )?(?:year|quarter) is (?:coming|approaching|near|here|close)\b"
)
_LEGAL_TERMS = (
    r"clauses?|termes?|terms|conditions?|resiliation|termination|avenants?|amendments?|redline\w*"
    r"|liability|responsabilite|penalit\w+|penalt\w+|negoci\w+|renegoci\w+|juridique|legal"
    r"|lawyers?|avocats?|review\w*|relecture|revue|redaction|draft\w*|renouvellement tacite"
    r"|auto-?renew\w*"
)
# A bare "contrat"/"contract" is not legal: it needs a legal-terms word within three words.
_LEGAL = (
    r"\b(?:juridiques?|clauses?|dpa|conditions generales|terms and conditions"
    r"|terms of (?:service|use)|cgv|cgu|nda|data processing agreement|avenants?|redline\w*"
    r"|liability|indemnit\w+|resiliation|governing law|droit applicable|jurisdiction|juridiction"
    r"|legal (?:team|review|department|terms|clauses?|requirements?|issues?|concerns?|counsel"
    r"|approval|sign-?off|check|validation)"
    r"|(?:service|equipe|revue|validation|departement|avis) legal\w*"
    rf"|(?:{_LEGAL_TERMS})\W+(?:\w+\W+){{0,3}}?(?:contrats?|contracts?)"
    rf"|(?:contrats?|contracts?)\W+(?:\w+\W+){{0,3}}?(?:{_LEGAL_TERMS}))\b"
)
_ONBOARDING = (
    r"\b(?:formations?|training|onboard\w*|deploiements?|rollout|roll-out|accompagnement"
    r"|mise en route|go-live|prise en main|mise en place|mise en oeuvre|mise en service"
    r"|implementation|deploy(?:ed|ing|ment|s)?|time to value|ramp-?up|kick-?off|workshops?"
    r"|ateliers?"
    r"|conduite du changement|change management|getting started|demarrage|tutoriels?|tutorials?"
    r"|former (?:les|nos|mes|vos|l'equipe|tout)|train (?:our|the|my|your|his|her|new|all)"
    r"|adoption)\b"
)
_SUPPORT = (
    r"(?<!\bi )(?<!\bi fully )\b(?:support"
    r"(?!\s+(?:de|du|d')\s*(?:presentation|cours|communication|vente|formation|marketing)\b)"
    r"(?!\s+(?:your|his|her|their)\s+(?:decision|choice|idea|opinion))"
    r"|sla|assistance|hotline|help ?desk|temps de reponse|response time"
    r"|service client|customer (?:service|success)|csm|astreinte|tickets?|reactivite"
    r"|interlocuteur dedie|dedicated (?:contact|account manager|csm|support)"
    r"|24/7|24x7|24h/24|7j/7|24 ?h ?/ ?24)\b"
)

_MASKS = {
    "timing": _rx(_TIMING_MASK),
    "price": _rx(_PRICE_MASK),
    "competitor": _rx(_COMPETITOR_MASK),
}

CATALOG: tuple[KnownDef, ...] = tuple(
    KnownDef(i, label, kind.value, desc, _rx(src), _MASKS.get(i))
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


def _def_hits(d: KnownDef, folded: str) -> list[str]:
    """Hits of a theme in a folded sentence, after blanking its documented false-positive spans."""
    if d.mask is not None:
        folded = d.mask.sub(lambda m: " " * len(m.group(0)), folded)
    return _hits(d.pattern, folded)


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
                hits = _def_hits(d, folded)
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
        n = len(_def_hits(d, folded)) if d else 0
        n += sum(folded.count(fold(t)) for t in extra_terms)
        if best is None or n > best[0]:
            best = (n, s)
    return best[1] if best else text.strip()
