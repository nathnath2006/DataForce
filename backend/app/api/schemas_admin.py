"""Schemas of the read-only admin endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt


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


class EditableLimit(BaseModel):
    key: str
    value: int | float  # what applies now (for a workspace: its own, else the global, else .env)
    default: int | float  # the `.env` value
    source: Literal["workspace", "global", "default"]
    min: float
    max: float
    unit: str
    description: str
    group: str
    kind: Literal["int", "float"]
    global_value: int | float | None = None  # workspace view only: the ceiling for this workspace
    updated_at: datetime | None = None
    updated_by: str | None = None  # superadmin view only
    workspace_editable: bool = True  # false = global only


class LimitUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # null = back to the default (or to the global value)
    value: StrictInt | StrictFloat | None = None


class UsageMetrics(BaseModel):
    calls: int
    failures: int
    input_tokens: int
    output_tokens: int
    p50_latency_ms: int | None
    cost_eur: float | None  # null until a price is set for the model
    avg_cost_per_call_eur: float | None
    unpriced_calls: int  # calls left out of the cost because their model has no price


class UsageUser(UsageMetrics):
    user_id: uuid.UUID | None  # null = the system (background jobs, CLI)
    name: str


class UsageModel(UsageMetrics):
    provider: str
    model: str
    price_set: bool
    input_per_mtok_eur: float | None
    output_per_mtok_eur: float | None


class UsageDay(UsageMetrics):
    day: date


class UsageDayUser(UsageMetrics):
    day: date
    user_id: uuid.UUID | None
    name: str


class UsagePurpose(UsageMetrics):
    purpose: str


class UsageWorkspace(UsageMetrics):
    workspace_id: uuid.UUID | None
    slug: str | None
    name: str | None


class UsageReport(BaseModel):
    days: int
    since: datetime
    totals: UsageMetrics
    by_user: list[UsageUser]
    by_model: list[UsageModel]
    by_day: list[UsageDay]
    by_day_user: list[UsageDayUser]
    by_purpose: list[UsagePurpose]


class UsageReportAll(UsageReport):
    by_workspace: list[UsageWorkspace]


class ModelPriceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["gemini", "anthropic"]
    model: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:\-]+$")
    input_per_mtok_eur: float = Field(ge=0, le=100_000, allow_inf_nan=False)
    output_per_mtok_eur: float = Field(ge=0, le=100_000, allow_inf_nan=False)


class ModelPriceOut(BaseModel):
    id: uuid.UUID
    provider: str
    model: str
    input_per_mtok_eur: float
    output_per_mtok_eur: float
    updated_at: datetime
