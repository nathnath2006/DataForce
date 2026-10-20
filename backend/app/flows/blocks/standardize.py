"""standardize: ordered text-cleaning operations on one or more columns. Deterministic text
rules only: no library, no network. Nulls stay null; other non-text cells are read as text."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

import pandas as pd

from app.flows.blocks._common import BlockError, BlockOutput, Ctx, require
from app.flows.schemas import StandardizeConfig, StandardizeView, StdColumnStat

# country -> (dial code, national trunk prefix, allowed lengths of the national number)
COUNTRIES: dict[str, tuple[str, str, tuple[int, int]]] = {
    "FR": ("33", "0", (9, 9)),
    "BE": ("32", "0", (8, 9)),
    "CH": ("41", "0", (9, 9)),
    "DE": ("49", "0", (10, 11)),
    "GB": ("44", "0", (10, 10)),
    "ES": ("34", "", (9, 9)),
    "IT": ("39", "", (9, 10)),
    "PT": ("351", "", (9, 9)),
    "NL": ("31", "0", (9, 9)),
    "US": ("1", "", (10, 10)),
    "CA": ("1", "", (10, 10)),
}
_SEPARATORS = re.compile(r"[\s.\-()/]")
_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")


def to_e164(value: str, country: str = "FR") -> str | None:
    """A simple rule, not a numbering-plan library. Separators (space . - ( ) /) are dropped.
    `+` or `00` start an international number (8 to 15 digits, no leading 0). Otherwise the value
    is national: the trunk prefix (0 for FR) is removed and the length must fit the country.
    Returns None when the value cannot be parsed."""
    dial, trunk, (lo, hi) = COUNTRIES[country]
    s = _SEPARATORS.sub("", value.strip())
    if s.startswith("+"):
        digits, intl = s[1:], True
    elif s.startswith("00"):
        digits, intl = s[2:], True
    else:
        digits, intl = s, False
    if not digits.isascii() or not digits.isdigit():
        return None
    if intl:
        if digits.startswith(dial + trunk) and trunk and len(digits) - len(dial) - 1 >= lo:
            digits = dial + digits[len(dial) + 1 :]  # +33 (0)6...: drop the written trunk 0
        if 8 <= len(digits) <= 15 and digits[0] != "0":
            return "+" + digits
        return None
    if trunk and digits.startswith(trunk):
        nat = digits[len(trunk) :]
    elif digits.startswith(dial) and lo <= len(digits) - len(dial) <= hi:
        nat = digits[len(dial) :]  # 33612345678: dial code written without the +
    else:
        nat = digits
    if lo <= len(nat) <= hi and nat[0] != "0":
        return "+" + dial + nat
    return None


def _title(s: str) -> str:
    return _WORD.sub(lambda m: m.group()[:1].upper() + m.group()[1:].lower(), s)


def _accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if unicodedata.category(c) != "Mn")


def _punct(s: str) -> str:
    return "".join(c for c in s if not unicodedata.category(c).startswith("P"))


SIMPLE: dict[str, Callable[[str], str | None]] = {
    "trim": str.strip,
    "collapse_spaces": lambda s: re.sub(r"\s+", " ", s),
    "lower": str.lower,
    "upper": str.upper,
    "title": _title,
    "remove_accents": _accents,
    "normalize_unicode": lambda s: unicodedata.normalize("NFC", s),
    "strip_punctuation": _punct,
    "empty_to_null": lambda s: None if s.strip() == "" else s,
    "email": lambda s: s.strip().lower(),
}


def run(cfg: StandardizeConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    require(df, cfg.columns)
    if len(cfg.mapping) > 200:
        raise BlockError("the value map has at most 200 pairs")
    if "map_values" in cfg.operations and not cfg.mapping:
        raise BlockError("map_values needs at least one pair in the map")
    mapping = (
        {k.casefold(): v for k, v in cfg.mapping.items()}
        if cfg.mapping_ignore_case
        else cfg.mapping
    )
    out = df.copy()
    stats: list[StdColumnStat] = []
    for col in dict.fromkeys(cfg.columns):
        target = col if cfg.output == "overwrite" else f"{col}_std"
        if target != col and target in df.columns:
            raise BlockError(f"the input already has a column named '{target}'")
        ctx.check()
        flagged = 0
        res: list[str | None] = []
        changed = nulled = 0
        for i, raw in enumerate(df[col].tolist()):
            if i % 1000 == 0:
                ctx.check()
            if raw is None or raw is pd.NA or (isinstance(raw, float) and raw != raw):
                res.append(None)
                continue
            orig = raw if isinstance(raw, str) else str(raw)
            v: str | None = orig
            for op in cfg.operations:
                if v is None:
                    break
                if op == "map_values":
                    key = v.casefold() if cfg.mapping_ignore_case else v
                    v = mapping.get(key, v)
                elif op == "phone_e164":
                    e = to_e164(v, cfg.country)
                    if e is None:
                        flagged += 1  # left as is
                    else:
                        v = e
                else:
                    v = SIMPLE[op](v)
            res.append(v)
            if v is None:
                nulled += 1
            if v != raw:
                changed += 1
        out[target] = pd.Series(res, index=df.index, dtype=object)
        stats.append(
            StdColumnStat(
                column=col, output=target, n_changed=changed, n_null=nulled, n_flagged=flagged
            )
        )
    warnings = [
        f"{s.n_flagged} values in '{s.column}' are not valid phone numbers; left as they were"
        for s in stats
        if s.n_flagged
    ]
    return BlockOutput(
        frames={"out": out},
        view=StandardizeView(n_rows=len(df), columns=stats),
        warnings=warnings,
    )
