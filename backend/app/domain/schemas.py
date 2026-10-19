"""Cross-module data contracts (pydantic v2).

Modules exchange these types, never ORM objects. The demo generator, the stats engine, the CLI and
(later) the API / MCP server all speak them, so every analysis result is a plain JSON-serializable
object: the "AI friendly" access layer returns exact results, not prose.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    DealStage,
    Dimension,
    JobFunction,
    LeadSource,
    Metric,
    RecordSource,
    Segment,
    Seniority,
    StatStatus,
    UserRole,
)


# --- CRM write models (what the services accept) -------------------------------------------------
class UserIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    role: UserRole = UserRole.USER


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    domain: str | None = Field(default=None, max_length=253)
    industry: str | None = Field(default=None, max_length=100)
    segment: Segment | None = None
    employee_count: int | None = Field(default=None, ge=0, le=10_000_000)  # int4-safe
    region: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    source: RecordSource = RecordSource.MANUAL
    external_ref: str | None = Field(default=None, max_length=200)  # e.g. TamTam id, SIREN


class ContactIn(BaseModel):
    """Third-party personal data: strict minimum (name, title, company, source). No email/phone."""

    account_id: UUID
    full_name: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    reports_to_id: UUID | None = None  # manual org chart link (the certain one)
    source: RecordSource = RecordSource.MANUAL
    source_ref: str | None = Field(default=None, max_length=500)  # where it comes from


class DealIn(BaseModel):
    account_id: UUID
    owner_id: UUID | None = None
    name: str = Field(min_length=1, max_length=300)
    amount_eur: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    stage: DealStage = DealStage.PROSPECTING
    lead_source: LeadSource | None = None
    created_on: date
    closed_on: date | None = None
    lost_reason: str | None = Field(default=None, max_length=500)
    source: RecordSource = RecordSource.MANUAL


# --- CRM read models -----------------------------------------------------------------------------
class AccountRead(AccountIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    company_id: UUID | None = None  # M2a: the company this account belongs to
    created_at: datetime


class ContactRead(ContactIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    title_function: JobFunction | None = None
    title_seniority: Seniority | None = None
    title_source: str | None = None  # M2b: dictionary | llm | manual
    title_flag: str | None = None  # M2b: why the classification needs a look
    created_at: datetime


class DealRead(DealIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    created_at: datetime


class NoteRead(BaseModel):
    """A note (on a contact) or a comment (on an account). Append-only: a correction is a new row
    with `corrects_id` set; a delete only sets `deleted_at`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    author_id: UUID | None
    body: str
    created_at: datetime
    corrects_id: UUID | None = None
    deleted_at: datetime | None = None
    deleted_by_id: UUID | None = None


# --- stats engine --------------------------------------------------------------------------------
class GateConfig(BaseModel):
    """Snapshot of the 'not verified' gates used for a result (from Settings).

    Validated like Settings: a NaN or out-of-range threshold would make every gate pass."""

    model_config = ConfigDict(allow_inf_nan=False)

    confidence: float = Field(default=0.95, gt=0.5, lt=1.0)
    fdr_alpha: float = Field(default=0.05, gt=0.0, lt=0.5)
    min_n: int = Field(default=30, ge=1)
    min_wins: int = Field(default=10, ge=0)
    min_losses: int = Field(default=10, ge=0)
    max_ci_halfwidth_pts: float = Field(default=15.0, gt=0, le=50)
    max_ci_rel_halfwidth: float = Field(default=0.30, gt=0, le=1)
    bootstrap_resamples: int = Field(default=2000, ge=200)
    random_seed: int = 42


class StatValue(BaseModel):
    """One computed number with its uncertainty and its verification status."""

    metric: Metric
    value: float | None  # None when it cannot be computed (e.g. 0 rows)
    ci_low: float | None = None
    ci_high: float | None = None
    n: int  # rows actually used
    method: str  # e.g. "wilson", "bootstrap-percentile median"
    status: StatStatus
    reasons: list[str] = []  # why not verified (empty when verified)
    details: dict[str, Any] = {}  # e.g. {"wins": 12, "losses": 30, "excluded_missing": 3}


class GroupStats(BaseModel):
    dimension: Dimension
    group: str  # category label; "(missing)" is never a group, it is counted separately
    n_deals: int
    stats: dict[Metric, StatValue]


class EffectFinding(BaseModel):
    """'Group X differs from the rest on metric M.'

    Only `verified` findings may be shown as facts."""

    dimension: Dimension
    group: str
    metric: Metric
    group_value: float | None
    rest_value: float | None
    diff: float | None  # group - rest (rate points for win rate, days for cycle, EUR for amount)
    diff_ci_low: float | None
    diff_ci_high: float | None
    p_value: float | None
    q_value: float | None  # Benjamini-Hochberg adjusted across the whole scan
    test: str  # e.g. "fisher-exact", "mann-whitney-u"
    n_group: int
    n_rest: int
    direction: Literal["higher", "lower", "none"]
    status: StatStatus
    reasons: list[str] = []


class ScanReport(BaseModel):
    workspace_id: UUID | None
    created_at: datetime
    n_deals: int
    n_closed: int
    n_open: int
    gates: GateConfig
    overall: dict[Metric, StatValue]
    groups: list[GroupStats]
    findings: list[EffectFinding]  # every comparison tested, verified or not
    missing: dict[str, int] = {}  # field -> rows with a missing value
    notes: list[str] = []


# --- synthetic demo ground truth -----------------------------------------------------------------
class PlantedEffect(BaseModel):
    dimension: Dimension
    group: str
    metric: Metric
    direction: Literal["higher", "lower"]
    magnitude: str  # human-readable, e.g. "+25 pts win rate", "x2.5 cycle length"


class MeetingTruth(BaseModel):
    """What the generator planted in one synthetic transcript (M2b)."""

    document_key: str
    account_key: str
    deal_key: str | None = None
    themes: list[str] = []  # planted theme ids (see M2Truth.theme_ids)
    # (speaker contact key, manager contact key) for "I report to X" style sentences
    org_statements: list[tuple[str, str]] = []
    # (contact key, "champion" | "blocker" | "decision_maker")
    signals: list[tuple[str, str]] = []


class M2Truth(BaseModel):
    """Answer key for M2b: titles, org chart and meetings. Kept out of the CRM."""

    roles: dict[str, str] = {}  # contact key -> role (app.demo.names.ROLE_TITLES key)
    org: dict[str, str | None] = {}  # contact key -> true manager key (full tree)
    links_removed: list[str] = []  # contact keys whose manual link is absent from the CRM
    theme_ids: list[str] = []
    meetings: list[MeetingTruth] = []


class GroundTruth(BaseModel):
    variant: Literal["planted", "noise"]
    seed: int
    n_accounts: int
    n_contacts: int
    n_deals: int
    planted: list[PlantedEffect]  # empty for the noise variant
    null_dimensions: list[Dimension]  # dimensions with no effect at all
    # Every (dimension, metric) cell the generator plants NO dependence into (null_dimensions x
    # all metrics, plus e.g. segment x win_rate). Any verified finding there is a false positive.
    # Cells that are neither planted nor null (e.g. outbound's lower win rate, which mirrors the
    # planted inbound effect) are real-but-not-required: neither a miss nor a false positive.
    null_cells: list[tuple[Dimension, Metric]] = []
    small_groups: list[tuple[Dimension, str]] = []  # must come out "not verified" (too few rows)
    notes: list[str] = []
    m2: M2Truth | None = None  # M2b answer key (titles, org chart, meetings)


# --- LLM usage + enrichment (kept from v1) -------------------------------------------------------
LLMPurpose = Literal[
    "title_classification",
    "theme_naming",
    "explanation",
    "deal_summary",
    "action_items",
    "embedding",
    "assistant",
    "connection_test",
]


class LLMCallRecord(BaseModel):
    provider: str
    model: str
    purpose: LLMPurpose
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int
    success: bool
    error: str | None = None


class EnrichmentRequest(BaseModel):
    full_name: str
    company_name: str
    company_domain: str | None = None
    want: list[Literal["email", "mobile"]] = ["email"]


class EnrichmentResult(BaseModel):
    provider: str
    email: str | None = None
    mobile: str | None = None
    credits_used: float = 0.0
    source: str | None = None
    raw_tool: str | None = None  # MCP tool name that served it
    # SR2-04/10: set when the server's credit figure was invalid or above the ceiling, or its
    # result could not be parsed; `notes` says why (never contains contact values).
    anomalous: bool = False
    notes: list[str] = []
