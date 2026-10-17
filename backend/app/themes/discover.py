"""Theme discovery (method v2): TF-IDF + NMF over the distinct sentences of the chunks, with person
names masked and a FR->EN sales glossary. Deterministic (fixed seed); the only clock use is a
time budget on preparation.

No text leaves the computer: this is plain scikit-learn.
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import TfidfVectorizer

from app.themes.glossary import apply_glossary, fold, tokens

MAX_CHUNKS = 20_000
MAX_UNITS = 20_000  # sentences
TIME_BUDGET_S = 20.0
DEFAULT_K = 12
MIN_WEIGHT = 0.2
MIN_CHUNKS_PER_THEME = 3
MIN_DOCS_PER_THEME = 3
N_TOP_TERMS = 10
N_EXCERPTS = 3
SEED = 42
MIN_INPUT_CHUNKS = 4

_FR = """alors au aucun aussi autre avant avec avez avoir bon car ce cela ces ceux chaque ci comme
comment dans des du donc dont elle elles en encore est et etaient etait ete etre eu fait faire
fois ici il ils je la le les leur leurs lui ma mais me meme mes moi mon ne nos notre nous on ou
par pas peu peut plus pour pourquoi qu que quel quelle quels qui sa sans se ses si son sont sur
ta te tes toi ton tout tous tres tu un une vos votre vous oui non bien ok voila ca cette cet
avons ont suis sommes etes serait sera ai as aux jai nest cest moi bonjour merci donc deja puis
ensuite alors peut etre vais va vont allons faut falloir veux veut voudrais pouvez peux""".split()
_EN = """a about after all also am an and any are as at be because been before being but by can
could did do does doing for from had has have having he her here hers him his how i if in into
is it its just me more most my no nor not of on once only or other our out over own same she
should so some such than that the their them then there these they this those through to too
under until up very was we were what when where which while who whom why will with would you
your yeah yes okay ok thanks thank hello hi right sure like know think going get got let well
one two""".split()


# Conversational filler: never a theme on its own.
_FILLERS = """interessant surtout clair air team around us vraiment effectivement exactement
absolument evidemment bref genre franchement justement carrement completement parfaitement super
top genial perfect great nice good sounds interesting totally absolutely exactly basically
actually really obviously maybe perhaps probably definitely indeed anyway guess mean kind sort
stuff thing things lot lots way bit little pretty quite rather already still even autour
equipe chose choses truc trucs peu beaucoup entendu compris""".split()
FILLERS = frozenset(fold(w) for w in _FILLERS)

STOP_WORDS: list[str] = sorted({fold(w) for w in _FR + _EN} | FILLERS)


class ThemeError(ValueError):
    """Not enough text to find themes (the message is safe to show)."""


@dataclass(frozen=True)
class FoundTheme:
    seq: int  # 1-based, by decreasing size
    top_terms: list[str]
    members: list[tuple[int, float]] = field(default_factory=list)  # (input index, weight)
    excerpts: list[tuple[int, str]] = field(default_factory=list)  # (input index, exact sentence)


@dataclass(frozen=True)
class Dropped:
    top_terms: list[str]
    n_chunks: int


@dataclass(frozen=True)
class Discovery:
    themes: list[FoundTheme]
    dropped: list[Dropped]
    n_used: int
    n_unassigned: int  # chunks used that belong to no kept theme


_SENT = re.compile(r"[^.!?\u2026\n]+(?:[.!?\u2026]+|\n|$)")
_WORD = re.compile(r"[^\W\d_]+|\d+")


def sentences(text: str) -> list[str]:
    """Non-empty sentences of `text`, trimmed; each an exact substring."""
    out = []
    for m in _SENT.finditer(text):
        piece = m.group(0)
        s = m.start() + len(piece) - len(piece.lstrip())
        e = m.end() - (len(piece) - len(piece.rstrip()))
        if e > s:
            out.append(text[s:e])
    return out


def name_tokens(names: Sequence[str]) -> frozenset[str]:
    """Folded tokens of person names (single letters ignored)."""
    return frozenset(t for n in names for t in tokens(n) if len(t) > 1)


def mask_names(text: str, names: Sequence[str]) -> str:
    """`text` without any word that is a token of one of `names` (for text sent to the AI)."""
    bad = name_tokens(names)
    if not bad:
        return text
    out = _WORD.sub(lambda m: "" if set(tokens(m.group(0))) & bad else m.group(0), text)
    return re.sub(r"\s{2,}", " ", out).strip()


def prepare(sentence: str, bad: frozenset[str] = frozenset()) -> str:
    """Folded, name-masked, glossed form of a sentence (what the vectoriser sees)."""
    return " ".join(apply_glossary([w for w in tokens(sentence) if w not in bad]))


def discover(
    texts: Sequence[str],
    k: int,
    names: Sequence[str] = (),
    doc_ids: Sequence[object] | None = None,
    skip: frozenset[tuple[int, int]] = frozenset(),
) -> Discovery:
    """Themes of `texts` (in the given order; the result depends on it only through ties).

    `names` are person names to mask; `doc_ids` (one per text) lets excerpts come from distinct
    documents. `skip` holds (chunk index, sentence index) pairs left out (already explained by a
    known theme). Topics of mostly stop words or fillers, or in fewer than 3 documents, are dropped.
    """
    if len(texts) < MIN_INPUT_CHUNKS:
        raise ThemeError("not enough transcript text to find themes")
    bad = name_tokens(names)
    t0 = time.monotonic()
    units: list[tuple[int, str, str]] = []  # (chunk index, original sentence, prepared)
    n_used = 0
    for ci, text in enumerate(texts[:MAX_CHUNKS]):
        if len(units) >= MAX_UNITS or time.monotonic() - t0 > TIME_BUDGET_S:
            break
        n_used = ci + 1
        for si, s in enumerate(sentences(text)):
            if (ci, si) in skip:
                continue
            units.append((ci, s, prepare(s, bad)))
    fit_on = sorted({p for _, _, p in units if p})
    vectorizer = TfidfVectorizer(
        lowercase=False,
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.6,
        stop_words=STOP_WORDS,
        sublinear_tf=True,
    )
    try:
        fit = vectorizer.fit_transform(fit_on)
    except ValueError:
        raise ThemeError("not enough shared vocabulary to find themes") from None
    n_components = min(k, fit.shape[0] - 1, fit.shape[1])
    if n_components < 1:
        raise ThemeError("not enough shared vocabulary to find themes")
    model = NMF(n_components=n_components, init="nndsvda", random_state=SEED, max_iter=800)
    model.fit(fit)
    w = model.transform(vectorizer.transform([p for _, _, p in units]))
    h = model.components_
    names_out = vectorizer.get_feature_names_out()
    sums = w.sum(axis=1)
    norm = w / np.where(sums > 0, sums, 1.0)[:, None]
    norm[sums <= 0] = 0.0

    raw: list[tuple[list[str], list[tuple[int, float]], list[tuple[int, str]]]] = []
    for c in range(n_components):
        order = np.argsort(-h[c], kind="stable")[:N_TOP_TERMS]
        terms = [str(names_out[i]) for i in order if h[c][i] > 0]
        best: dict[int, float] = {}
        cand: list[tuple[float, int, int]] = []  # (-weight, unit index, chunk index)
        for u, (ci, _, _) in enumerate(units):
            wt = float(norm[u, c])
            if wt >= MIN_WEIGHT:
                best[ci] = max(best.get(ci, 0.0), wt)
                cand.append((-wt, u, ci))
        members = sorted(best.items())
        cand.sort()
        raw.append((terms, members, _pick_excerpts(cand, units, doc_ids)))

    def keep(t: list[str], m: list[tuple[int, float]]) -> bool:
        if len(m) < MIN_CHUNKS_PER_THEME or not t:
            return False
        words = [w for term in t[:6] for w in term.split()]
        if sum(w in FILLERS for w in words) * 2 >= len(words):
            return False
        n_docs = len({doc_ids[i] if doc_ids is not None else i for i, _ in m})
        return n_docs >= MIN_DOCS_PER_THEME

    ok = [(t, m, e) for t, m, e in raw if keep(t, m)]
    dropped = [Dropped(t, len(m)) for t, m, _ in raw if not keep(t, m)]
    ok.sort(key=lambda r: -len(r[1]))  # stable: ties keep the component order
    themes = [FoundTheme(i + 1, t, m, e) for i, (t, m, e) in enumerate(ok)]
    assigned = {i for t in themes for i, _ in t.members}
    return Discovery(themes, dropped, n_used, n_used - len(assigned))


def _pick_excerpts(
    cand: list[tuple[float, int, int]],
    units: list[tuple[int, str, str]],
    doc_ids: Sequence[object] | None,
) -> list[tuple[int, str]]:
    """Up to N_EXCERPTS highest-weight distinct sentences, from distinct documents if possible."""
    chosen: list[tuple[int, str]] = []
    seen_text: set[str] = set()
    seen_doc: set[object] = set()
    rest: list[tuple[int, str]] = []
    for _, u, ci in cand:
        sent = units[u][1]
        if sent in seen_text:
            continue
        seen_text.add(sent)
        doc = doc_ids[ci] if doc_ids is not None else ci
        if doc in seen_doc:
            rest.append((ci, sent))
            continue
        seen_doc.add(doc)
        chosen.append((ci, sent))
        if len(chosen) == N_EXCERPTS:
            return chosen
    return (chosen + rest)[:N_EXCERPTS]


def best_sentence(text: str, top_terms: Sequence[str]) -> str:
    """The sentence of `text` with the most distinct words of the top terms (first on ties), after
    the same folding and glossary as discovery; an exact substring of `text`."""
    wanted = {w for term in top_terms for w in term.split()}
    best: tuple[int, str] | None = None
    for s in sentences(text):
        score = len(set(apply_glossary(tokens(s))) & wanted)
        if best is None or score > best[0]:
            best = (score, s)
    return best[1] if best else text.strip()
