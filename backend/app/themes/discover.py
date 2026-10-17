"""Theme discovery: TF-IDF + NMF over chunks. Pure and deterministic (fixed seed, no clock).

No text leaves the computer: this is plain scikit-learn.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import TfidfVectorizer

MAX_CHUNKS = 20_000
MIN_WEIGHT = 0.15
MIN_CHUNKS_PER_THEME = 3
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


def _fold(word: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", word.lower()) if not unicodedata.combining(c)
    )


STOP_WORDS: list[str] = sorted({_fold(w) for w in _FR + _EN})


class ThemeError(ValueError):
    """Not enough text to find themes (the message is safe to show)."""


@dataclass(frozen=True)
class FoundTheme:
    seq: int  # 1-based, by decreasing size
    top_terms: list[str]
    members: list[tuple[int, float]] = field(default_factory=list)  # (input index, weight)


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


def discover(texts: Sequence[str], k: int) -> Discovery:
    """Themes of `texts` (in the given order; the result depends on it only through ties)."""
    if len(texts) < MIN_INPUT_CHUNKS:
        raise ThemeError("not enough transcript text to find themes")
    texts = list(texts[:MAX_CHUNKS])
    vectorizer = TfidfVectorizer(
        strip_accents="unicode",
        lowercase=True,
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.6,
        stop_words=STOP_WORDS,
    )
    try:
        tfidf = vectorizer.fit_transform(texts)
    except ValueError:
        raise ThemeError("not enough shared vocabulary to find themes") from None
    n_terms = tfidf.shape[1]
    n_components = min(k, len(texts) - 1, n_terms)
    if n_components < 1:
        raise ThemeError("not enough shared vocabulary to find themes")
    model = NMF(n_components=n_components, init="nndsvda", random_state=SEED, max_iter=400)
    w = model.fit_transform(tfidf)
    h = model.components_
    names = vectorizer.get_feature_names_out()

    sums = w.sum(axis=1)
    safe = np.where(sums > 0, sums, 1.0)
    norm = w / safe[:, None]
    best = norm.argmax(axis=1)
    best_w = norm[np.arange(len(texts)), best]

    raw: list[tuple[list[str], list[tuple[int, float]]]] = []
    for c in range(n_components):
        order = np.argsort(-h[c], kind="stable")[:N_TOP_TERMS]
        terms = [str(names[i]) for i in order if h[c][i] > 0]
        members = [
            (int(i), float(best_w[i]))
            for i in range(len(texts))
            if best[i] == c and sums[i] > 0 and best_w[i] >= MIN_WEIGHT
        ]
        raw.append((terms, members))

    kept = [(t, m) for t, m in raw if len(m) >= MIN_CHUNKS_PER_THEME and t]
    dropped = [Dropped(t, len(m)) for t, m in raw if not (len(m) >= MIN_CHUNKS_PER_THEME and t)]
    kept.sort(key=lambda tm: -len(tm[1]))  # stable: ties keep the component order
    themes = [FoundTheme(i + 1, t, m) for i, (t, m) in enumerate(kept)]
    n_assigned = sum(len(t.members) for t in themes)
    return Discovery(themes, dropped, len(texts), len(texts) - n_assigned)


# --- excerpts ------------------------------------------------------------------------------------
_SENT = re.compile(r"[^.!?…\n]+(?:[.!?…]+|\n|$)")
_WORD = re.compile(r"[^\W\d_]+|\d+")


def best_sentence(text: str, top_terms: Sequence[str]) -> str:
    """The sentence of `text` with the most distinct words of the top terms (first on ties); an
    exact substring of `text`."""
    wanted = {_fold(w) for term in top_terms for w in term.split()}
    best: tuple[int, int, int] | None = None
    for m in _SENT.finditer(text):
        s, e = m.start(), m.end()
        piece = text[s:e]
        s += len(piece) - len(piece.lstrip())
        e -= len(piece) - len(piece.rstrip())
        if e <= s:
            continue
        score = len({_fold(w) for w in _WORD.findall(text[s:e])} & wanted)
        if best is None or score > best[0]:
            best = (score, s, e)
    if best is None:
        return text.strip()
    return text[best[1] : best[2]]
