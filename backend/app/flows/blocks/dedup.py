"""dedup: fuzzy deduplication of one text column (analysis only, never merges CRM records).

Values are normalised (casefold, accents and punctuation removed, trailing legal suffixes such as
SAS, Inc, Ltd, GmbH, Corp, Group and leading articles the / le / la / les dropped). Rows whose
normalised values share a blocking prefix or the first letter of their last word are compared
with Jaro-Winkler or a Levenshtein ratio; pairs at or above the threshold are
linked (single linkage). The master of a group is its most complete row, then the longest text,
then the first row. Values with different numbers never match. Groups are candidates to review.
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

from app.flows.blocks._common import BlockError, BlockOutput, Ctx, require
from app.flows.schemas import DedupConfig

MAX_ROWS = 50_000
MAX_BLOCK = 500  # distinct values per block compared exhaustively
MAX_KEY = 100  # characters of a normalised key that are compared
CHECK_EVERY = 1_000  # pairs between cancellation checks
NEIGHBOURS = 50  # sorted-neighbourhood window used for a larger block
LEGAL = frozenset(
    "sas sarl sa sasu eurl snc inc incorporated ltd limited llc llp plc gmbh ag bv nv srl spa "
    "corp corporation co company group groupe holding holdings".split()
)
ARTICLES = frozenset("the le la les l".split())
_DIGITS = re.compile(r"\d+")
_PUNCT = re.compile(r"[^0-9a-z]+")


def normalise(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text).casefold())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    toks = _PUNCT.sub(" ", s).split()
    while len(toks) > 1 and toks[-1] in LEGAL:
        toks.pop()
    while len(toks) > 1 and toks[0] in ARTICLES:
        toks.pop(0)  # "The Acme" and "Acme" compare equal
    return " ".join(toks)


def same_digits(a: str, b: str) -> bool:
    """Names that differ only in their numbers ("Store 101", "Store 104") are never a match."""
    return _DIGITS.findall(a) == _DIGITS.findall(b)


def jaro(a: str, b: str) -> float:
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if not la or not lb:
        return 0.0
    rng = max(la, lb) // 2 - 1
    ma, mb = [False] * la, [False] * lb
    m = 0
    for i, ch in enumerate(a):
        for j in range(max(0, i - rng), min(lb, i + rng + 1)):
            if not mb[j] and b[j] == ch:
                ma[i] = mb[j] = True
                m += 1
                break
    if not m:
        return 0.0
    t, j = 0, 0
    for i in range(la):
        if ma[i]:
            while not mb[j]:
                j += 1
            if a[i] != b[j]:
                t += 1
            j += 1
    t //= 2
    return (m / la + m / lb + (m - t) / m) / 3


def jaro_winkler(a: str, b: str) -> float:
    j = jaro(a, b)
    p = 0
    for x, y in zip(a[:4], b[:4], strict=False):
        if x != y:
            break
        p += 1
    return j + p * 0.1 * (1 - j)


def levenshtein_ratio(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1 - prev[-1] / max(len(a), len(b))


def _find(parent: list[int], i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def run(cfg: DedupConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    require(df, [cfg.column])
    warnings: list[str] = []
    if len(df) > MAX_ROWS:
        warnings.append(f"rows capped at {MAX_ROWS}: only the first {MAX_ROWS} were deduplicated")
        df = df.head(MAX_ROWS)
    df = df.reset_index(drop=True)
    sim = jaro_winkler if cfg.method == "jaro_winkler" else levenshtein_ratio
    raw = df[cfg.column]
    keys = [normalise(v)[:MAX_KEY] if isinstance(v, str) else "" for v in raw]
    uniq = sorted({k for k in keys if k})
    pos = {k: i for i, k in enumerate(uniq)}
    parent = list(range(len(uniq)))
    # two blocking keys: the leading characters, and the first character of the last word
    # (a pair is compared if it shares either; the second pass skips pairs the first one saw)
    blocks: dict[str, list[int]] = {}
    tails: dict[str, list[int]] = {}
    for k in uniq:
        blocks.setdefault(k[: cfg.block_prefix], []).append(pos[k])
        tails.setdefault(k.split()[-1][0], []).append(pos[k])
    big = 0
    pairs = 0
    p = cfg.block_prefix
    for second, members in [(False, m) for m in blocks.values()] + [
        (True, m) for m in tails.values()
    ]:
        ctx.check()
        big_block = len(members) > MAX_BLOCK
        big += big_block
        for x, i in enumerate(members):
            a = uniq[i]
            stop = min(len(members), x + 1 + NEIGHBOURS) if big_block else len(members)
            for j in members[x + 1 : stop]:
                pairs += 1
                if pairs % CHECK_EVERY == 0:
                    ctx.check()
                b = uniq[j]
                if second and a[:p] == b[:p]:
                    continue  # already compared through the first blocking key
                if not same_digits(a, b):
                    continue
                if min(len(a), len(b)) / max(len(a), len(b)) < cfg.threshold - 0.5:
                    continue  # cheap length bound: cannot reach the threshold
                if sim(a, b) >= cfg.threshold:
                    ri, rj = _find(parent, i), _find(parent, j)
                    if ri != rj:
                        parent[max(ri, rj)] = min(ri, rj)
    if big:
        warnings.append(
            f"{big} very large block(s) (over {MAX_BLOCK} values): only neighbouring values "
            "were compared; "
            "use a longer blocking prefix"
        )
    complete = df.notna().sum(axis=1).to_numpy()
    group_of: dict[int, int] = {}
    groups: list[int | None] = []
    members_by_group: dict[int, list[int]] = {}
    next_id = 0
    for r, k in enumerate(keys):
        if k:
            root = _find(parent, pos[k])
            if root not in group_of:
                next_id += 1
                group_of[root] = next_id
            g = group_of[root]
        else:
            next_id += 1
            g = next_id
        groups.append(g)
        members_by_group.setdefault(g, []).append(r)
    master = [False] * len(df)
    for rows in members_by_group.values():
        best = max(
            rows,
            key=lambda r: (
                int(complete[r]),
                len(raw.iat[r]) if isinstance(raw.iat[r], str) else 0,
                -r,
            ),
        )
        master[best] = True
    master_key = {g: keys[next(r for r in rs if master[r])] for g, rs in members_by_group.items()}
    similarity = [
        1.0 if not keys[r] or keys[r] == master_key[g] else round(sim(keys[r], master_key[g]), 4)
        for r, g in enumerate(groups)
    ]
    out = df.copy()
    for name in ("dedup_group", "is_master", "dedup_similarity"):
        if name in out.columns:
            raise BlockError(f"the input already has a column named '{name}'")
    out["dedup_group"] = pd.array(groups, dtype="int64")
    out["is_master"] = master
    out["dedup_similarity"] = similarity  # to the group's master; low values are weak links
    n_dup = len(df) - sum(master)
    if n_dup:
        warnings.append(
            f"{n_dup} rows are candidates to review as duplicates of a master row "
            "(CRM records are not merged); dedup_similarity shows how close each one is"
        )
    return BlockOutput(frames={"out": out}, warnings=warnings)
