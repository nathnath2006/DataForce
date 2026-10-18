"""Shared enums. Stored as plain text in Postgres (no PG enum types: easier migrations)."""

from __future__ import annotations

from enum import StrEnum


# --- CRM ---------------------------------------------------------------------------------------
class DealStage(StrEnum):
    """Fixed pipeline (custom pipelines are out of v1)."""

    PROSPECTING = "prospecting"
    QUALIFICATION = "qualification"
    PROPOSAL = "proposal"
    NEGOTIATION = "negotiation"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"


OPEN_STAGES = (
    DealStage.PROSPECTING,
    DealStage.QUALIFICATION,
    DealStage.PROPOSAL,
    DealStage.NEGOTIATION,
)
CLOSED_STAGES = (DealStage.CLOSED_WON, DealStage.CLOSED_LOST)


class LeadSource(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    REFERRAL = "referral"
    PARTNER = "partner"
    EVENT = "event"
    OTHER = "other"


class Segment(StrEnum):
    """Account size segment (from employee count: <50 / 50-999 / 1000+)."""

    SMB = "smb"
    MIDMARKET = "midmarket"
    ENTERPRISE = "enterprise"


class RecordSource(StrEnum):
    """Where a CRM row comes from. Third-party personal data always keeps its origin."""

    MANUAL = "manual"
    DEMO = "demo"  # synthetic generator, announced as such
    IMPORT = "import"  # imported document (M2)
    TAMTAM = "tamtam"  # TamTam connector (M3)
    REGISTRY = "registry"  # public company registry (recherche-entreprises.api.gouv.fr, M2a)


class UserRole(StrEnum):
    ADMIN = "admin"
    USER = "user"


# --- title normalisation (columns exist in M1, filled in M2) -----------------------------------
class JobFunction(StrEnum):
    SALES = "sales"
    MARKETING = "marketing"
    EXECUTIVE = "executive"
    FINANCE = "finance"
    OPERATIONS = "operations"
    TECH = "tech"
    HR = "hr"
    OTHER = "other"
    UNKNOWN = "unknown"


class Seniority(StrEnum):
    C_LEVEL = "c_level"
    VP = "vp"
    HEAD = "head"  # head of / director
    MANAGER = "manager"
    INDIVIDUAL = "individual"
    UNKNOWN = "unknown"


# --- analysis ----------------------------------------------------------------------------------
class StatStatus(StrEnum):
    VERIFIED = "verified"
    NOT_VERIFIED = "not_verified"  # a gate failed: shown with its reasons, never as a fact


class Metric(StrEnum):
    WIN_RATE = "win_rate"  # closed deals only
    CYCLE_DAYS = "cycle_days"  # created -> closed, median, closed deals with both dates
    DEAL_AMOUNT = "deal_amount"  # EUR, median, deals with an amount


class Dimension(StrEnum):
    """Deal attributes the engine segments on. All categorical."""

    LEAD_SOURCE = "lead_source"
    SEGMENT = "segment"  # from the account
    INDUSTRY = "industry"  # from the account
    REGION = "region"  # from the account
    OWNER = "owner"  # the sales rep (app user)
    AMOUNT_BAND = "amount_band"  # derived: <10k / 10-50k / 50k+


class RunKind(StrEnum):
    DEMO_GENERATE = "demo_generate"
    STATS_SCAN = "stats_scan"
    FLOW_RUN = "flow_run"  # M2a: an analysis flow was run (params: flow id, node; result: summary)
    TITLE_NORMALIZE = "title_normalize"  # M2b
    ORG_RULES = "org_rules"  # M2b: org-chart proposals from rules and meetings
    THEME_ANALYSIS = "theme_analysis"  # M2b
    AGENT_CALL = "agent_call"  # M3a: one MCP / agent tool call (params: tool + args; summary)


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


# --- connectors (M1b) --------------------------------------------------------------------------
class ConnectorProvider(StrEnum):
    TAMTAM = "tamtam"


class ConnectorStatus(StrEnum):
    CONNECTED = "connected"
    EXPIRED = "expired"  # refresh failed: the user must click "Connect" again
    ERROR = "error"


class ChannelKind(StrEnum):
    EMAIL = "email"
    MOBILE = "mobile"


# --- M2b: titles, org-chart proposals, transcripts and themes -------------------------------------
class TitleSource(StrEnum):
    DICTIONARY = "dictionary"
    LLM = "llm"  # classified by the AI once, cached and flagged for review
    MANUAL = "manual"  # set by a user: never overwritten by a normalisation run


class ProposalKind(StrEnum):
    REPORTS_TO = "reports_to"
    CHAMPION = "champion"
    BLOCKER = "blocker"
    DECISION_MAKER = "decision_maker"


class ProposalOrigin(StrEnum):
    RULE = "rule"  # same account + normalised titles
    MEETING = "meeting"  # a sentence in a transcript (the excerpt is kept)


class ProposalStatus(StrEnum):
    PROPOSED = "proposed"
    AMBIGUOUS = "ambiguous"  # several candidates: never guessed, the candidates are listed
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ThemeKind(StrEnum):
    OBJECTION = "objection"
    NEED = "need"
    COMPETITOR = "competitor"
    TIMING = "timing"
    OTHER = "other"
