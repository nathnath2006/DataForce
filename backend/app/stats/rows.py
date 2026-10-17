"""Plain input rows for the stats engine (no ORM, no DB)."""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date

from app.domain.enums import DealStage, Dimension

BAND_LOW = "<10k"
BAND_MID = "10-50k"
BAND_HIGH = "50k+"


@dataclass(frozen=True, slots=True)
class DealRow:
    """One deal flattened with its account and owner. `won` is None while the deal is open."""

    id: uuid.UUID | str | int
    won: bool | None
    stage: str | None = None
    lead_source: str | None = None
    segment: str | None = None
    industry: str | None = None
    region: str | None = None
    owner: str | None = None
    amount: float | None = None
    created_on: date | None = None
    closed_on: date | None = None

    @property
    def is_closed(self) -> bool:
        return self.won is not None

    @property
    def cycle_days(self) -> float | None:
        """Days from creation to close; closed deals with both dates only."""
        if self.won is None or self.created_on is None or self.closed_on is None:
            return None
        return float((self.closed_on - self.created_on).days)

    @property
    def amount_band(self) -> str | None:
        if self.amount is None:
            return None
        if self.amount < 10_000:
            return BAND_LOW
        if self.amount < 50_000:
            return BAND_MID
        return BAND_HIGH


def won_from_stage(stage: str | None) -> bool | None:
    if stage == DealStage.CLOSED_WON:
        return True
    if stage == DealStage.CLOSED_LOST:
        return False
    return None


def value_of(row: DealRow, dim: Dimension) -> str | None:
    """Category of `row` on `dim`; None when missing (empty strings count as missing)."""
    if dim is Dimension.AMOUNT_BAND:
        v = row.amount_band
    else:
        v = getattr(row, dim.value)
    if v is None:
        return None
    v = str(v)
    return v if v.strip() else None


@dataclass(frozen=True, slots=True)
class CleanResult:
    rows: list[DealRow]
    duplicates: int  # rows dropped because their deal id was already seen (first one is kept)
    negative_cycle: int  # closed_on before created_on: the dates are ignored for cycle
    invalid_amount: int  # NaN, infinite or negative amounts: treated as missing


def clean_rows(rows: Iterable[DealRow]) -> CleanResult:
    """Validate rows once: dedupe by id, drop impossible cycles and amounts. Idempotent."""
    seen: set[object] = set()
    out: list[DealRow] = []
    dup = neg = bad_amt = 0
    for r in rows:
        if r.id in seen:
            dup += 1
            continue
        seen.add(r.id)
        if r.amount is not None and (not math.isfinite(r.amount) or r.amount < 0):
            r = replace(r, amount=None)
            bad_amt += 1
        if (
            r.won is not None
            and r.created_on is not None
            and r.closed_on is not None
            and r.closed_on < r.created_on
        ):
            r = replace(r, created_on=None, closed_on=None)
            neg += 1
        out.append(r)
    return CleanResult(out, dup, neg, bad_amt)
