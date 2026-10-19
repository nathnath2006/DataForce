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
            # A first name alone needs 3+ letters (SR12-04); multi-word aliases keep >= 2.
            if len(name) >= (2 if " " in name else 3):
                seen.setdefault(name, set()).add(c.id)
    return {a: next(iter(ids)) for a, ids in seen.items() if len(ids) == 1}


_S = r"\s+"
# A conditional or hypothetical word earlier in the same sentence ("If I report to Paul, ...")
# means the statement is not an assertion.
_HYPOTHETICAL = re.compile(
    r"\b(?:if|si|unless|whether|suppose|supposing|imagine|what if|when|quand|lorsque|au cas ou)\b"
)

# Role nouns for "my boss" style appositions (direct line only; no n+2 / "boss's boss").
_EN_ROLE = (
    rf"(?:direct{_S})?(?:line{_S})?(?:boss|manager|supervisor|superior|lead|n\+1)(?!'s)(?!\w)"
)
_FR_ROLE = (
    rf"(?:manager|n\+1|chef|cheffe|boss|patron|patronne|responsable|directeur|directrice"
    rf"|superieur|superieure|superieur\(e\))(?:{_S}hierarchique)?(?:{_S}direct(?:e)?)?(?!\w)"
)
# Optional role apposition after a name: "Paula, our CFO," / "Paula, notre CEO,".
_APPO = r"(?:,[^,.!?;\n]{1,40}?,|,)?"
_EN_ADV = (
    rf"(?:(?:still|really|quite|rather|very|a{_S}bit|somewhat|pretty|strongly|firmly|totally"
    rf"|completely|mostly|actually|honestly|generally){_S})*"
)
_FR_ADV = (
    rf"(?:(?:plutot|assez|tres|vraiment|encore|toujours|franchement|clairement|fortement"
    rf"|totalement|completement|un{_S}peu|plus{_S}ou{_S}moins|aussi|toujours){_S})*"
)
_EN_OBJ = (
    rf"(?:project|deal|proposal|proposition|offer|renewal|purchase|contract|solution|tool|platform"
    rf"|initiative|case|recommendation|request|rollout|plan|choice|quote|pilot|purchase|order"
    rf"|business{_S}case)s?"
)
_FR_OBJ = (
    r"(?:dossier|projet|sujet|proposition|offre|renouvellement|contrat|demande|solution|outil"
    r"|plateforme|initiative|achat|deal|choix|devis|recommandation|besoin|pilote|commande)s?"
)
_FR_TARGET = (
    rf"(?:(?:ce|cet|cette|le|la|l'|les|notre|votre|son|sa)\s*(?:\w+{_S}){{0,1}}?{_FR_OBJ}"
    r"|ca|cela|ceci)\b"
)
_EN_TARGET = (
    rf"(?:(?:this|it|that)\b|(?:the|our|your|this|that|his|her|their){_S}"
    rf"(?:\w+{_S}){{0,2}}?{_EN_OBJ}\b)"
)
_EN_CHAMP_V = (
    rf"(?:champion|push|back|sponsor|defend|support|advocate{_S}for|argue{_S}for|vouch{_S}for"
    rf"|make{_S}the{_S}case{_S}for|push{_S}for|stand{_S}behind|get{_S}behind)"
)
_EN_ADVB = (
    rf"(?:(?:definitely|certainly|gladly|personally|also|totally|really|happily|absolutely){_S})?"
)

# (id, kind, subject, regex source with {N} for the name). subject: "speaker" = first person,
# "name" = the person named, "name_manager" = speaker/name pairs for reports_to.
_PATTERNS: list[tuple[str, str, str, str]] = [
    # reports_to, subject is the speaker unless noted
    (
        "en_i_report_to",
        "reports_to",
        "speaker",
        rf"\bi{_S}(?:now{_S}|also{_S})?report{_S}(?:(?:directly|solely|mainly|functionally){_S})?"
        rf"(?:to|into){_S}{{N}}(?!'s\b)",
    ),
    (
        "en_my_boss_is",
        "reports_to",
        "speaker",
        rf"\bmy{_S}(?:boss|manager|line{_S}manager){_S}is{_S}{{N}}(?!'s\b)",
    ),
    (
        "en_is_my_boss",
        "reports_to",
        "speaker",
        rf"{{N}}{_S}is{_S}my{_S}(?:line{_S})?(?:boss|manager)\b",
    ),
    (
        "en_i_work_under",
        "reports_to",
        "speaker",
        rf"\bi{_S}(?:(?:now|also|directly|currently){_S})*work{_S}(?:directly{_S})?(?:under"
        rf"|for){_S}"
        rf"{{N}}(?!'s\b)",
    ),
    (
        "en_my_boss_name",
        "reports_to",
        "speaker",
        rf"(?<!\w)my{_S}{_EN_ROLE}(?:,{_S}|{_S}){{N}}(?!'s\b)",
    ),
    (
        "en_name_my_boss",
        "reports_to",
        "speaker",
        rf"{{N}}{_APPO}{_S}(?:(?:who|which|that){_S}is{_S})?my{_S}{_EN_ROLE}",
    ),
    (
        "en_manages_my_team",
        "reports_to",
        "speaker",
        rf"{{N}}{_S}(?:(?:who|that){_S})?(?:manages|runs|leads|heads|oversees){_S}my{_S}"
        rf"(?:team|department|unit|group)\b",
    ),
    (
        "en_in_team_of",
        "reports_to",
        "speaker",
        rf"\bi(?:'m|{_S}am){_S}(?:part{_S}of|in){_S}{{N}}'s{_S}team\b",
    ),
    (
        "fr_je_reporte_a",
        "reports_to",
        "speaker",
        rf"\bje{_S}reporte{_S}(?:directement{_S})?a{_S}{{N}}",
    ),
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
        rf"\bje{_S}suis{_S}(?:(?:directement|aussi){_S})?sous{_S}la{_S}responsabilite"
        rf"{_S}(?:directe{_S})?(?:de{_S}|d'){{N}}",
    ),
    (
        "fr_sous_la_direction",
        "reports_to",
        "speaker",
        rf"\b(?:je{_S}suis|je{_S}travaille|j'evolue){_S}(?:(?:directement|aussi){_S})?sous{_S}"
        rf"(?:la{_S}(?:direction|supervision|houlette)|l'autorite){_S}(?:directe{_S})?(?:de{_S}"
        rf"|d'){{N}}",
    ),
    (
        "fr_rattache_a",
        "reports_to",
        "speaker",
        rf"\bje{_S}suis{_S}(?:(?:directement|aussi|toujours){_S})?rattache(?:e)?{_S}"
        rf"(?:(?:directement|hierarchiquement|fonctionnellement){_S})?(?:a"
        rf"|au{_S}pres{_S}de){_S}{{N}}",
    ),
    (
        "fr_je_travaille_sous",
        "reports_to",
        "speaker",
        rf"\bje{_S}travaille{_S}(?:directement{_S})?(?:sous"
        rf"|pour){_S}(?:les{_S}ordres{_S}de{_S})?{{N}}",
    ),
    (
        "fr_dans_equipe_de",
        "reports_to",
        "speaker",
        rf"\b(?:je{_S}suis{_S}dans|je{_S}fais{_S}partie{_S}de){_S}l'equipe{_S}(?:de{_S}|d'){{N}}",
    ),
    (
        "fr_gere_mon_equipe",
        "reports_to",
        "speaker",
        rf"{{N}}{_S}(?:qui{_S})?(?:gere|dirige|manage|encadre|supervise|pilote){_S}"
        rf"(?:directement{_S})?(?:mon|ma){_S}(?:equipe|service|pole|departement)\b",
    ),
    (
        "fr_mon_manager_nom",
        "reports_to",
        "speaker",
        rf"(?<!\bde )(?<!\bdu )(?<!\bd')\b(?:mon|ma){_S}{_FR_ROLE}(?:,{_S}|{_S}){{N}}(?!'s\b)",
    ),
    (
        "fr_nom_ma_directrice",
        "reports_to",
        "speaker",
        rf"{{N}}(?:{_APPO}{_S}(?:(?:c'est|qui{_S}est){_S})?|{_S}(?:c'est|qui{_S}est){_S})"
        rf"(?:mon|ma){_S}{_FR_ROLE}",
    ),
    # champion (first person)
    (
        "en_ill_champion",
        "champion",
        "speaker",
        rf"\bi(?:'ll|{_S}will){_S}{_EN_ADVB}{_EN_CHAMP_V}{_S}{_EN_TARGET}",
    ),
    (
        "en_going_to_champion",
        "champion",
        "speaker",
        rf"\bi(?:'m{_S}going{_S}to|{_S}am{_S}going{_S}to|'m{_S}gonna|'m{_S}happy{_S}to"
        rf"|{_S}am{_S}happy{_S}to|'d{_S}be{_S}happy{_S}to|'m{_S}glad{_S}to|'m{_S}ready{_S}to"
        rf"|{_S}want{_S}to|{_S}plan{_S}to){_S}{_EN_ADVB}{_EN_CHAMP_V}{_S}{_EN_TARGET}",
    ),
    (
        "fr_je_vais_pousser",
        "champion",
        "speaker",
        rf"\bje{_S}(?:vais|veux|compte){_S}(?:(?:bien|aussi|donc|vraiment|personnellement){_S})?"
        rf"(?:pousser|porter|defendre|soutenir|appuyer|parrainer|sponsoriser|plaider{_S}pour)"
        rf"{_S}{_FR_TARGET}",
    ),
    (
        "fr_je_vais_le_defendre",
        "champion",
        "speaker",
        rf"\bje{_S}(?:vais|veux|compte){_S}(?:(?:bien|aussi|donc|vraiment){_S})?(?:le|la|l'"
        rf"|les){_S}?"
        rf"(?:pousser|defendre|soutenir|appuyer|parrainer|sponsoriser)\b",
    ),
    # blocker (about NAME)
    (
        "en_is_against",
        "blocker",
        "name",
        rf"{{N}}{_APPO}{_S}(?:is|seems|remains|appears|'s){_S}{_EN_ADV}(?:against"
        rf"|opposed(?:{_S}to)?"
        rf"|reluctant|resistant|skeptical|sceptical|hesitant|unconvinced|not{_S}convinced"
        rf"|not{_S}sold|blocking|wary)\b",
    ),
    (
        "fr_bloque",
        "blocker",
        "name",
        rf"{{N}}(?:{_S}(?:bloque|n'est{_S}pas{_S}convaincu(?:e)?)\b"
        rf"|{_APPO}{_S}(?:est|reste|semble|parait){_S}{_FR_ADV}(?:contre|reticent(?:e)?"
        rf"|oppose(?:e)?|hostile|sceptique|frileu(?:x|se)|defavorable|resistant(?:e)?"
        rf"|peu{_S}convaincu(?:e)?|pas{_S}convaincu(?:e)?|pas{_S}d'accord)(?![\w-]))",
    ),
    (
        "en_refused",
        "blocker",
        "name",
        rf"{{N}}{_APPO}{_S}(?:has{_S}|had{_S})?(?:refused|rejected|vetoed|blocked|turned{_S}down"
        rf"|shot{_S}down|frozen){_S}(?:the|this|our|that|my|your|his|her|their){_S}",
    ),
    (
        "fr_a_refuse",
        "blocker",
        "name",
        rf"{{N}}{_APPO}{_S}(?:a|avait){_S}(?:refuse|bloque|rejete|gele|oppose{_S}son{_S}veto{_S}a"
        rf"|dit{_S}non{_S}a){_S}(?:l'|le{_S}|la{_S}|les{_S}|cette{_S}|ce{_S}|cet{_S}|notre{_S}"
        rf"|votre{_S}|mon{_S}|ma{_S}|toute{_S}|tout{_S})",
    ),
    (
        "en_im_against",
        "blocker",
        "speaker",
        rf"\bi(?:'m|{_S}am){_S}{_EN_ADV}(?:against|opposed{_S}to|reluctant|skeptical|sceptical"
        rf"|hesitant|unconvinced|not{_S}convinced|not{_S}sold)\b",
    ),
    (
        "fr_je_suis_contre",
        "blocker",
        "speaker",
        rf"\bje{_S}(?:suis|reste){_S}{_FR_ADV}(?:contre|reticent(?:e)?|sceptique|oppose(?:e)?{_S}a"
        rf"|defavorable|frileu(?:x|se)|peu{_S}convaincu(?:e)?)(?![\w-])"
        rf"|\bje{_S}ne{_S}suis{_S}pas{_S}(?:(?:vraiment|tres|encore|trop){_S})?convaincu(?:e)?\b",
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
        rf"\bc'est{_S}{{N}}{_S}qui{_S}(?:decide|valide|signe|tranche|arbitre"
        rf"|prend{_S}la{_S}decision"
        rf"|a{_S}le{_S}dernier{_S}mot|donne{_S}le{_S}feu{_S}vert)\b",
    ),
    (
        "en_final_call_is_with",
        "decision_maker",
        "name",
        rf"\b(?:final|last|ultimate){_S}(?:call|decision|say|word|sign-?off){_S}(?:is|lies|rests)"
        rf"{_S}(?:(?:ultimately|really|entirely){_S})?(?:with|on|up{_S}to|in{_S}the{_S}hands{_S}of)"
        rf"{_S}{{N}}",
    ),
    (
        "en_decision_rests_with",
        "decision_maker",
        "name",
        rf"\bthe{_S}(?:(?:final|last|ultimate){_S})?(?:call|decision|say|sign-?off)"
        rf"{_S}(?:(?:ultimately|really){_S})?(?:rests|lies|sits|belongs|falls|comes{_S}down)"
        rf"{_S}(?:with|to|on){_S}{{N}}",
    ),
    (
        "en_has_final_say",
        "decision_maker",
        "name",
        rf"{{N}}{_APPO}{_S}(?:has|holds|gets){_S}(?:the{_S})?(?:final|last|ultimate)"
        rf"{_S}(?:say|word|sign-?off|authority)\b",
    ),
    (
        "en_signs_off",
        "decision_maker",
        "name",
        rf"{{N}}{_APPO}{_S}(?:signs|approves|will{_S}sign|signs{_S}off{_S}on|will{_S}approve)"
        rf"{_S}(?:all|every|any|the|each|those|these|our|each){_S}(?:\w+{_S}){{0,2}}?"
        rf"(?:contracts?|deals?|purchases?|orders?|budgets?|spend|renewals?|agreements?|quotes?)\b",
    ),
    (
        "en_decides",
        "decision_maker",
        "name",
        rf"{{N}}{_APPO}{_S}(?:decides|will{_S}decide){_S}(?:on|about|whether|which|what|if"
        rf"|everything|alone|ultimately|in{_S}the{_S}end|the|all)\b",
    ),
    (
        "fr_decision_revient_a",
        "decision_maker",
        "name",
        rf"\b(?:la{_S}(?:decision|validation|signature)|le{_S}(?:dernier{_S}mot|choix|arbitrage))"
        rf"{_S}(?:finale?{_S})?(?:(?:revient|appartient|incombe|reste){_S}(?:toujours{_S}"
        rf"|in{_S}fine{_S})?"
        rf"(?:a|au){_S}|est{_S}(?:entre{_S}les{_S}mains{_S}(?:de{_S}|d')"
        rf"|du{_S}ressort{_S}(?:de{_S}|d')"
        rf"|chez{_S}|a{_S})){{N}}",
    ),
    (
        "fr_signe_les_contrats",
        "decision_maker",
        "name",
        rf"{{N}}{_APPO}{_S}(?:signe|valide|arbitre|tranche|approuve){_S}"
        rf"(?:tou(?:s|te|tes)?{_S}|les{_S}|le{_S}|la{_S}|l'|chaque{_S}|ces{_S}|ses{_S}|nos{_S})"
        rf"(?:\w+{_S}){{0,2}}?(?:contrats?|achats?|commandes?|devis|budgets?|depenses?|decisions?"
        rf"|renouvellements?|accords?|dossiers?)\b",
    ),
    (
        "fr_a_le_dernier_mot",
        "decision_maker",
        "name",
        rf"{{N}}{_APPO}{_S}(?:a{_S}le{_S}dernier{_S}mot|decide{_S}(?:de{_S}tout"
        rf"|en{_S}dernier{_S}ressort"
        rf"|seule?|au{_S}final|finalement|in{_S}fine))\b",
    ),
    (
        "en_i_decide",
        "decision_maker",
        "speaker",
        rf"\bi(?:'m|{_S}am){_S}the{_S}(?:one|person|guy|decision{_S}maker){_S}(?:who|that)"
        rf"{_S}(?:decides|signs|makes{_S}the{_S}(?:final{_S})?(?:call|decision))"
        rf"|\bi{_S}(?:make|have|hold){_S}the{_S}(?:final{_S})?(?:call|decision|say)\b"
        rf"|\bthe{_S}(?:final{_S})?(?:call|decision|say){_S}is{_S}mine\b",
    ),
    (
        "fr_cest_moi_qui_decide",
        "decision_maker",
        "speaker",
        rf"\bc'est{_S}moi{_S}qui{_S}(?:decide|arbitre|signe|tranche|valide"
        rf"|ai{_S}le{_S}dernier{_S}mot"
        rf"|prends{_S}la{_S}decision)\b|\bje{_S}suis{_S}(?:le|la|l'){_S}?(?:decideu[rs]e?"
        rf"|decisionnaire)\b",
    ),
]

# Reports-to statements that are negated or past: checked in the sentence before the match.
_PAST_OR_NEG = re.compile(
    r"\b(?:used{_S}to|previously|formerly|no{_S}longer|ex|anciennement|ancien|ancienne|precedent\w*"
    r"|previous|former|avant|jadis|jamais|never)\b".replace("{_S}", r"\s+")
)
_NEGATION = re.compile(r"\b(?:not|never|ne|jamais)\b|n't\b|\bn'|\bpas\b")

PATTERN_IDS = tuple(p[0] for p in _PATTERNS)


def _compile(src: str, names_key: tuple[str, ...]) -> re.Pattern[str]:
    alt = "|".join(re.escape(n).replace(r"\ ", r"\s+") for n in names_key)
    body = src.replace("{N}", rf"(?<!\w)(?P<name>{alt})(?!\w)")
    return re.compile(body)


_BOUNDARY = ".!?\n"
_NEXT_WORD = re.compile(r"[ \t]+(\S)")
_HYPHEN_LETTER = re.compile(r"-[^\W\d_]")


def _wrong_person(original: str, alias: str, start: int, end: int) -> bool:
    """True when the matched alias is only part of a longer name in the ORIGINAL text:
    "Marie Curie" (alias "marie"), "Jean-Pierre" (alias "jean"), "Anne-Marie" (alias "marie")."""
    if _HYPHEN_LETTER.match(original, end):
        return True
    if start >= 2 and original[start - 1] == "-" and original[start - 2].isalpha():
        return True
    if " " in alias:
        return False
    nxt = _NEXT_WORD.match(original, end)
    return nxt is not None and nxt.group(1).isalpha() and nxt.group(1).isupper()


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
    compiled: list[tuple[str, str, str, str, re.Pattern[str]]] | None = None
    for chunk in sorted(chunks, key=lambda c: (str(c.document_id), c.char_start)):
        if chunk.contact_id is None or chunk.contact_id not in ids:
            continue
        doc_text = document_texts.get(chunk.document_id)
        if doc_text is None:
            continue
        folded = fold(chunk.text)
        if compiled is None:  # once per call (= per account), reused across its chunks
            compiled = [
                (
                    pid,
                    kind,
                    subject,
                    src,
                    _compile(src, names_key) if "{N}" in src else _compile_plain(src),
                )
                for pid, kind, subject, src in _PATTERNS
                if "{N}" in src or subject != "name"
            ]
        for pid, kind, subject, src, rx in compiled:
            for m in rx.finditer(folded):
                named = alias.get(re.sub(r"\s+", " ", m.group("name"))) if "{N}" in src else None
                if "{N}" in src and named is None:
                    continue
                if "{N}" in src and _wrong_person(
                    chunk.text,
                    re.sub(r"\s+", " ", m.group("name")),
                    m.start("name"),
                    m.end("name"),
                ):
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
                if _HYPOTHETICAL.search(folded[s : m.start()]):
                    continue
                if kind == "reports_to":
                    if _PAST_OR_NEG.search(folded[s : m.end()]) or _NEGATION.search(
                        folded[max(s, m.start() - 40) : m.end()]
                    ):
                        continue
                elif subject == "speaker" and _NEGATION.search(
                    folded[max(s, m.start() - 25) : m.start()]
                ):
                    continue
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
