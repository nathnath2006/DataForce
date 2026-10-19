"""Schemas of the data-quality endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class QualitySegment(BaseModel):
    kind: Literal["ok", "warn", "bad", "unknown"]
    label: str
    count: int


class QualityCheck(BaseModel):
    id: Literal["managers", "titles", "amounts", "companies"]
    label: str
    total: int
    segments: list[QualitySegment]


class QualityOut(BaseModel):
    checks: list[QualityCheck]
