"""Dictionary classification of a normalised title (no AI)."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import JobFunction, Seniority
from app.titles.dictionary import RULES, SENIORITY_RANK, STOPWORDS, canon
from app.titles.normalize import normalize_title

FLAG_NO_TITLE = "no title"
FLAG_UNKNOWN = "unknown title"


@dataclass(frozen=True)
class TitleClass:
    normalized: str
    function: JobFunction
    seniority: Seniority
    source: str  # "dictionary" or "none"
    flag: str | None
    matched: bool


def classify_normalized(normalized: str) -> TitleClass:
    if not normalized:
        return TitleClass(
            normalized, JobFunction.UNKNOWN, Seniority.UNKNOWN, "none", FLAG_NO_TITLE, False
        )
    tokens = [canon(t) for t in normalized.split() if t not in STOPWORDS]
    taken = [False] * len(tokens)
    functions: list[JobFunction] = []
    seniorities: list[Seniority] = []
    for rule in RULES:
        n = len(rule.words)
        for i in range(len(tokens) - n + 1):
            if any(taken[i : i + n]) or tuple(tokens[i : i + n]) != rule.words:
                continue
            for j in range(i, i + n):
                taken[j] = True
            if rule.function is not None and rule.function not in functions:
                functions.append(rule.function)
            if rule.seniority is not None:
                seniorities.append(rule.seniority)
    matched = bool(functions or seniorities)
    # executive is the weakest function: "Directeur general marketing" is a marketing title
    if len(functions) > 1 and JobFunction.EXECUTIVE in functions:
        functions.remove(JobFunction.EXECUTIVE)
    seniority = max(seniorities, key=SENIORITY_RANK.__getitem__) if seniorities else None
    if len(functions) > 1:
        names = ", ".join(f.value for f in functions)
        return TitleClass(
            normalized, JobFunction.UNKNOWN, seniority or Seniority.UNKNOWN, "dictionary",
            f"ambiguous function: {names}", True,
        )  # fmt: skip
    if not functions:
        unknown_sen = seniority or Seniority.UNKNOWN
        return TitleClass(
            normalized, JobFunction.UNKNOWN, unknown_sen, "none", FLAG_UNKNOWN, matched
        )
    return TitleClass(
        normalized, functions[0], seniority or Seniority.INDIVIDUAL, "dictionary", None, True
    )


def classify_title(title: str | None) -> TitleClass:
    return classify_normalized(normalize_title(title))
