"""Schemas of the read-only admin endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class AdminTable(BaseModel):
    name: str
    bytes: int
    rows_estimate: int


class AdminDatabase(BaseModel):
    size_bytes: int
    size_mb: float
    quota_mb: int
    used_pct: float | None
    tables: list[AdminTable]


class AdminSchema(BaseModel):
    current: str | None
    head: str | None
    up_to_date: bool


class AdminLimit(BaseModel):
    name: str
    value: int | float
    description: str


class AdminOverview(BaseModel):
    database: AdminDatabase
    schema_status: AdminSchema
    limits: list[AdminLimit]


class AdminRun(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    error: str | None
    summary: str
    stale: bool


class AdminRuns(BaseModel):
    runs: list[AdminRun]
    stale_after_s: int


class AdminUsageRow(BaseModel):
    provider: str
    model: str
    purpose: str
    calls: int
    failures: int
    input_tokens: int
    output_tokens: int


class AdminTodayRow(BaseModel):
    purpose: str
    calls: int
    daily_cap: int | None


class AdminAiUsage(BaseModel):
    source: str
    days: int
    rows: list[AdminUsageRow]
    today: list[AdminTodayRow]
