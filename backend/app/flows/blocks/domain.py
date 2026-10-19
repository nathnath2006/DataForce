"""domain: the domain of an email or URL and a free-webmail flag. Pure text parsing: no DNS or MX
lookup, nothing leaves the process."""

from __future__ import annotations

import re

import pandas as pd

from app.flows.blocks._common import BlockError, BlockOutput, Ctx, require
from app.flows.schemas import DomainConfig

FREE_EXACT = frozenset(
    "gmail.com googlemail.com outlook.com outlook.fr live.com live.fr msn.com icloud.com me.com "
    "mac.com orange.fr free.fr wanadoo.fr laposte.net sfr.fr neuf.fr bbox.fr aol.com proton.me "
    "protonmail.com pm.me zoho.com mail.com yandex.com yandex.ru qq.com 163.com".split()
)
FREE_FAMILY = ("hotmail", "yahoo", "gmx", "ymail")  # hotmail.*, yahoo.*, gmx.*
_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def extract_domain(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    s = value.strip().casefold()
    if not s:
        return None
    if "@" in s:
        s = s.rsplit("@", 1)[1]
    else:
        s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s)
        s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
        s = s.rsplit("@", 1)[-1]
    s = s.split(":", 1)[0].strip(" .>\"'<")
    if s.startswith("www."):
        s = s[4:]
    return s if _HOST.match(s) else None


def is_free(domain: str) -> bool:
    if domain in FREE_EXACT:
        return True
    return domain.split(".", 1)[0] in FREE_FAMILY


def run(cfg: DomainConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    require(df, [cfg.column])
    for name in (cfg.alias, "is_free_webmail"):
        if name in df.columns:
            raise BlockError(f"the input already has a column named '{name}'")
    dom = [extract_domain(v) for v in df[cfg.column]]
    out = df.copy()
    out[cfg.alias] = pd.Series(dom, index=df.index, dtype=object)
    out["is_free_webmail"] = pd.Series(
        [None if d is None else is_free(d) for d in dom], index=df.index, dtype=object
    )
    bad = sum(1 for d, v in zip(dom, df[cfg.column], strict=True) if d is None and pd.notna(v))
    warnings = [f"{bad} values are not a valid email or URL"] if bad else []
    return BlockOutput(frames={"out": out}, warnings=warnings)
