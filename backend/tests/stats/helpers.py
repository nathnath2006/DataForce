"""Synthetic DealRow builders for the stats tests."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from app.stats.rows import DealRow

SOURCES = ["inbound", "outbound", "referral", "partner"]
SEGMENTS = ["smb", "midmarket", "enterprise"]
INDUSTRIES = ["saas", "retail", "health", "industry"]
REGIONS = ["north", "south", "east", "west"]
OWNERS = ["Ana", "Ben", "Chloe", "Dan", "Eve"]


def make_rows(
    seed: int,
    n: int = 200,
    *,
    win_p_inbound: float = 0.35,
    p_closed: float = 0.8,
    planted: bool = False,
) -> list[DealRow]:
    """Global-null data unless `planted`: then inbound wins more and enterprise cycles longer."""
    rng = np.random.default_rng(seed)
    rows: list[DealRow] = []
    for i in range(n):
        src = SOURCES[rng.integers(len(SOURCES))]
        seg = SEGMENTS[rng.integers(len(SEGMENTS))]
        closed = rng.random() < p_closed
        p = 0.35
        if planted and src == "inbound":
            p = 0.75
        if planted and src == "outbound":
            p = 0.10
        cycle = float(rng.lognormal(3.5, 0.5))
        if planted and seg == "enterprise":
            cycle *= 4
        created = date(2025, 1, 1) + timedelta(days=int(rng.integers(0, 300)))
        rows.append(
            DealRow(
                id=i,
                won=bool(rng.random() < p) if closed else None,
                lead_source=src,
                segment=seg,
                industry=INDUSTRIES[rng.integers(len(INDUSTRIES))],
                region=REGIONS[rng.integers(len(REGIONS))],
                owner=OWNERS[rng.integers(len(OWNERS))],
                amount=float(rng.lognormal(9.5, 0.8)),
                created_on=created,
                closed_on=created + timedelta(days=round(cycle)) if closed else None,
            )
        )
    return rows
