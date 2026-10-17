"""HTTP contract of the local API (M1b). The frontend's TypeScript types mirror this file.

Conventions (see docs/UI-CONTRACT.md):
* every workspace route is under /api/w/{ws}/..., `ws` being the workspace slug;
* lists answer `{"items": [...], "total": n}`;
* PATCH bodies are partial: only the fields sent are changed, an explicit null clears a field;
* errors answer `{"error": {"code": ..., "message": ...}}` (ErrorResponse);
* numbers come from code (SQL or the stats engine), never from an LLM.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.domain.enums import ChannelKind, DealStage, LeadSource, Segment, UserRole
from app.domain.schemas import (
    AccountRead,
    ContactRead,
    DealRead,
    NoteRead,
    ScanReport,
)

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"
BODY_MAX_CHARS = 20_000  # same cap as app.services._appendonly


class _In(BaseModel):
    """Request bodies: unknown fields are an error (a typo must not be silently ignored)."""

    model_config = ConfigDict(extra="forbid")


class Page[T](BaseModel):
    items: list[T]
    total: int


class ErrorBody(BaseModel):
    code: Literal[
        "not_found",
        "invalid_input",
        "conflict",
        "forbidden",
        "paid_lookup_refused",
        "connector_not_configured",
        "connector_error",
        "internal",
    ]
    message: str  # human readable; never contains a secret, a token or a stack trace


class ErrorResponse(BaseModel):
    error: ErrorBody


class Health(BaseModel):
    ok: bool
    version: str
    environment: str


# --- workspaces and users -------------------------------------------------------------------------
class WorkspaceOut(BaseModel):
    slug: str
    name: str
    is_demo: bool  # synthetic data: the UI shows a permanent banner
    created_at: datetime
    n_accounts: int
    n_contacts: int
    n_deals: int


class WorkspaceCreate(_In):
    slug: str = Field(pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
    email: str | None
    role: UserRole


class UserCreate(_In):
    display_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    role: UserRole = UserRole.USER


# --- accounts -------------------------------------------------------------------------------------
class AccountOut(AccountRead):
    n_contacts: int
    n_deals: int
    n_open_deals: int


class AccountCreate(_In):
    name: str = Field(min_length=1, max_length=300)
    domain: str | None = Field(default=None, max_length=253)
    industry: str | None = Field(default=None, max_length=100)
    segment: Segment | None = None
    employee_count: int | None = Field(default=None, ge=0, le=10_000_000)
    region: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, min_length=2, max_length=2)


class AccountUpdate(_In):
    """Partial. `name` cannot be cleared (sending null for it is invalid input)."""

    name: str | None = Field(default=None, min_length=1, max_length=300)
    domain: str | None = Field(default=None, max_length=253)
    industry: str | None = Field(default=None, max_length=100)
    segment: Segment | None = None
    employee_count: int | None = Field(default=None, ge=0, le=10_000_000)
    region: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, min_length=2, max_length=2)


# --- contacts and org chart -----------------------------------------------------------------------
class ContactOut(ContactRead):
    account_name: str
    reports_to_name: str | None
    n_direct_reports: int
    n_notes: int  # current (not deleted) notes
    n_channels: int  # stored enriched emails / mobiles


class ContactCreate(_In):
    account_id: UUID
    full_name: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    reports_to_id: UUID | None = None


class ContactUpdate(_In):
    """Partial. The manager is changed with PUT .../reports-to (cycle and account checks)."""

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=200)


class ReportsToUpdate(_In):
    manager_id: UUID | None  # null clears the link


class OrgChartNode(BaseModel):
    id: UUID
    full_name: str
    title: str | None
    reports_to_id: UUID | None
    source: str  # where the link comes from: manual / demo / import / tamtam


class OrgChartOut(BaseModel):
    account_id: UUID
    account_name: str
    nodes: list[OrgChartNode]  # flat; the UI builds the tree from reports_to_id


# --- deals ----------------------------------------------------------------------------------------
class DealOut(DealRead):
    account_name: str
    owner_name: str | None
    is_closed: bool
    cycle_days: int | None  # closed_on - created_on, when both are known


class DealCreate(_In):
    account_id: UUID
    owner_id: UUID | None = None
    name: str = Field(min_length=1, max_length=300)
    amount_eur: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    stage: DealStage = DealStage.PROSPECTING
    lead_source: LeadSource | None = None
    created_on: date
    closed_on: date | None = None
    lost_reason: str | None = Field(default=None, max_length=500)


class DealUpdate(_In):
    """Partial. The stage (and closed_on) is changed with PUT .../stage."""

    owner_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=300)
    amount_eur: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    lead_source: LeadSource | None = None
    created_on: date | None = None
    lost_reason: str | None = Field(default=None, max_length=500)


class StageUpdate(_In):
    stage: DealStage
    closed_on: date | None = None


# --- notes (on contacts) and comments (on accounts): append-only ----------------------------------
class NoteOut(NoteRead):
    author_name: str | None
    deleted_by_name: str | None


class NoteCreate(_In):
    body: str = Field(min_length=1, max_length=BODY_MAX_CHARS)
    author_id: UUID | None = None  # the "acting as" user picked in the UI (no login before M3)


class NoteCorrect(_In):
    body: str = Field(min_length=1, max_length=BODY_MAX_CHARS)
    author_id: UUID | None = None


# --- stats ----------------------------------------------------------------------------------------
class StageTotals(BaseModel):
    count: int
    amount_eur: float
    n_with_amount: int


class PipelineOut(BaseModel):
    """Exact SQL aggregates (facts: no interval, no gate)."""

    n_deals: int
    n_open: int
    n_closed: int
    n_won: int
    n_lost: int
    by_stage: dict[DealStage, StageTotals]
    total_amount_eur: float


class ScanOut(BaseModel):
    run_id: UUID
    report: ScanReport  # every comparison tested; only status == "verified" may be shown as fact


# --- connectors (TamTam over MCP, OAuth) ----------------------------------------------------------
class PricingOut(BaseModel):
    """Credits per lookup. Assumed from TamTam's public site until a real account confirms them."""

    email: float
    mobile: float
    ceiling: float  # ENRICHMENT_MAX_CREDITS_PER_CALL: nothing above is ever sent
    assumed: bool = True


class ToolOut(BaseModel):
    name: str
    description: str | None  # server text: sanitised and capped, shown as plain text only
    read_only: bool | None  # MCP annotation readOnlyHint, when the server publishes it
    destructive: bool | None  # MCP annotation destructiveHint
    allowed: bool  # in DataForce's allow-list: the only tools a lookup may ever call


class ConnectorOut(BaseModel):
    provider: Literal["tamtam"]
    status: Literal["not_connected", "connected", "expired", "error"]
    # How a contact lookup runs in THIS workspace: demo workspaces always use the fake provider
    # (their people are fictional), others use TamTam once connected.
    enrichment_mode: Literal["fake", "tamtam", "off"]
    secret_key_configured: bool  # false: connecting is impossible until `dataforce secrets init`
    resource: str  # the MCP URL
    issuer: str | None = None
    scope: str | None = None
    connected_at: datetime | None = None
    token_expires_at: datetime | None = None
    checked_at: datetime | None = None
    tools: list[ToolOut] | None = None  # from the last "Check connection"
    last_error: str | None = None
    pricing: PricingOut


class ConnectStart(BaseModel):
    authorize_url: str  # https URL on the allowed issuer; the browser navigates to it


# --- enrichment -----------------------------------------------------------------------------------
class EnrichRequest(_In):
    want: list[ChannelKind] = Field(min_length=1, max_length=2)
    # Explicit consent: must be the JSON literal true for any lookup that costs credits
    # ("yes", 1 or "true" are refused, not coerced).
    confirm_paid: StrictBool = False
    # The credit estimate the user saw and accepted; the server refuses if its own estimate is
    # higher (the price changed between display and click).
    max_credits: float = Field(ge=0, le=1000, allow_inf_nan=False)


class ChannelOut(BaseModel):
    id: UUID
    kind: ChannelKind
    value: str  # unsealed for display; never logged
    provider: str  # "tamtam_mcp" | "fake"
    credits_used: float
    raw_tool: str | None
    fetched_at: datetime


class EnrichResponse(BaseModel):
    mode: Literal["fake", "tamtam"]
    channels: list[ChannelOut]  # the channels stored by this lookup (empty: nothing found)
    credits_used: float
    anomalous: bool  # the server's credit figure or result looked wrong; see notes
    notes: list[str]
