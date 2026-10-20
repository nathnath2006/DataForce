"""regex: extract named groups, replace, match or split one text column.

Python's `re` cannot be interrupted, so the block refuses risky input up front:
* the pattern has at most 200 characters;
* cells are cut to 2,000 characters before matching;
* `check_pattern` rejects likely catastrophic backtracking. The heuristic (conservative, so it can
  refuse a few harmless patterns): an UNBOUNDED quantifier (`*`, `+`, `{n,}`) applied to a group
  that (a) contains another unbounded quantifier, as in `(a+)+`, `(a*)*`, `(.*x)*`, or (b) has
  alternatives where one is a prefix of another, as in `(a|aa)+`;
* `ctx.check()` runs every 1,000 rows."""

from __future__ import annotations

import re

import pandas as pd

from app.flows.blocks._common import BlockError, BlockOutput, Ctx, require
from app.flows.schemas import RegexConfig, RegexView

MAX_PATTERN = 200
MAX_CELL = 2000
_OPEN_RANGE = re.compile(r"\{\d*,\}")
_RANGE = re.compile(r"\{\d*(,\d*)?\}")


def _unbounded_at(p: str, i: int) -> bool:
    if i >= len(p):
        return False
    if p[i] in "*+":
        return True
    return p[i] == "{" and _OPEN_RANGE.match(p, i) is not None


def _alt_overlap(body: str) -> bool:
    """Do the top-level alternatives of a group body include one that is a prefix of another?"""
    alts: list[str] = []
    depth, start, i, in_cls = 0, 0, 0, False
    while i < len(body):
        c = body[i]
        if c == "\\":
            i += 2
            continue
        if in_cls:
            in_cls = c != "]"
        elif c == "[":
            in_cls = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "|" and depth == 0:
            alts.append(body[start:i])
            start = i + 1
        i += 1
    alts.append(body[start:])
    if len(alts) < 2:
        return False
    return any(a is not b and (a.startswith(b) or b.startswith(a)) for a in alts for b in alts)


def check_pattern(p: str) -> None:
    if len(p) > MAX_PATTERN:
        raise BlockError(f"the pattern has more than {MAX_PATTERN} characters")
    stack: list[list] = [[0, False]]  # [body start, contains an unbounded quantifier]
    i, in_cls = 0, False
    while i < len(p):
        c = p[i]
        if c == "\\":
            i += 2
            continue
        if in_cls:
            in_cls = c != "]"
        elif c == "[":
            in_cls = True
            if p[i + 1 : i + 2] == "^":
                i += 1
            if p[i + 1 : i + 2] == "]":
                i += 1
        elif c == "(":
            stack.append([i + 1, False])
        elif c == ")" and len(stack) > 1:
            start, inner = stack.pop()
            outer = _unbounded_at(p, i + 1)
            if outer and (inner or _alt_overlap(p[start:i])):
                raise BlockError(
                    "the pattern looks like it could backtrack catastrophically (an unbounded "
                    "repeat of a group that itself repeats or has overlapping alternatives, "
                    "such as (a+)+ or (a|aa)+); simplify it"
                )
            if inner or outer:
                stack[-1][1] = True
        elif _unbounded_at(p, i):
            stack[-1][1] = True
        i += 1


def compile_pattern(cfg: RegexConfig) -> re.Pattern[str]:
    check_pattern(cfg.pattern)
    try:
        rx = re.compile(cfg.pattern, re.IGNORECASE if cfg.ignore_case else 0)
        if cfg.mode == "replace":
            rx.sub(cfg.replacement, "")  # reports a bad group reference in the replacement
    except re.error as e:
        raise BlockError(f"invalid regular expression: {e}") from e
    except IndexError as e:
        raise BlockError(f"invalid replacement: {e}") from e
    return rx


def run(cfg: RegexConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    require(df, [cfg.column])
    rx = compile_pattern(cfg)
    if cfg.mode == "extract":
        names = list(rx.groupindex)
        if not names:
            raise BlockError("extract needs at least one named group, e.g. (?P<domain>[^@]+$)")
        new_cols = names
    elif cfg.mode == "split":
        new_cols = [f"{cfg.alias or cfg.column}_{k}" for k in range(1, cfg.split_into + 1)]
    elif cfg.mode == "match":
        new_cols = [cfg.alias or "regex_match"]
    else:
        new_cols = [cfg.alias or cfg.column]
    for n in new_cols:
        if n in df.columns and not (cfg.mode == "replace" and n == cfg.column):
            raise BlockError(f"the input already has a column named '{n}'")

    n_cells = n_matched = n_trunc = 0
    cols: list[list] = [[] for _ in new_cols]
    for i, raw in enumerate(df[cfg.column].tolist()):
        if i % 1000 == 0:
            ctx.check()
        if raw is None or raw is pd.NA or (isinstance(raw, float) and raw != raw):
            for c in cols:
                c.append(None)
            continue
        s = raw if isinstance(raw, str) else str(raw)
        if len(s) > MAX_CELL:
            s = s[:MAX_CELL]
            n_trunc += 1
        n_cells += 1
        if cfg.mode == "extract":
            m = rx.search(s)
            n_matched += m is not None
            for c, name in zip(cols, new_cols, strict=True):
                c.append(m.group(name) if m else None)
        elif cfg.mode == "match":
            hit = rx.search(s) is not None
            n_matched += hit
            cols[0].append(hit)
        elif cfg.mode == "replace":
            new, k = rx.subn(cfg.replacement, s)
            n_matched += k > 0
            cols[0].append(new)
        else:
            parts = rx.split(s, maxsplit=cfg.split_into - 1)
            n_matched += len(parts) > 1
            parts = (parts + [None] * cfg.split_into)[: cfg.split_into]
            for c, v in zip(cols, parts, strict=True):
                c.append(v)
    out = df.copy()
    for name, vals in zip(new_cols, cols, strict=True):
        out[name] = pd.Series(vals, index=df.index, dtype=object)
    warnings = []
    if n_trunc:
        warnings.append(f"{n_trunc} cells were cut to {MAX_CELL} characters before matching")
    return BlockOutput(
        frames={"out": out},
        view=RegexView(
            mode=cfg.mode,
            n_cells=n_cells,
            n_matched=n_matched,
            match_rate=(n_matched / n_cells) if n_cells else None,
            n_truncated=n_trunc,
            new_columns=new_cols,
        ),
        warnings=warnings,
    )
