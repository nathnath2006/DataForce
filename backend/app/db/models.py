"""SQLAlchemy 2.0 ORM models: the minimal CRM (PostgreSQL + pgvector).

Every business table carries `workspace_id`: a workspace is one team's data (and each synthetic
demo dataset is its own workspace), so the tool can be opened to TamTam clients later without a
schema rewrite. Enum-like columns are plain text holding app.domain.enums values. Alembic
migrations must mirror this file exactly.

Notes (on a contact) and comments (on an account) are APPEND-ONLY, enforced by a DB trigger
(see the migration): a correction is a new row pointing at the corrected one (`corrects_id`), a
delete only sets `deleted_at` / `deleted_by_id` once. The single exception is GDPR erasure of a
contact or account, which hard-deletes through the cascade inside a transaction that set
`SET LOCAL dataforce.erasure = 'on'` (services only).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 768  # must equal Settings.embedding_dim (pgvector columns arrive in M2)


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def _workspace_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False)


class Workspace(Base):
    __tablename__ = "workspace"
    __table_args__ = (
        CheckConstraint("setup_state IN ('preparing')", name="ck_workspace_setup_state"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    setup_state: Mapped[str | None] = mapped_column(
        String(16)
    )  # 'preparing' while filling; NULL = ready
    created_at: Mapped[datetime] = _created()


class AppUser(Base):
    """A member of the sales team (deal owner, note author). Auth columns arrive in M3."""

    __tablename__ = "app_user"
    __table_args__ = (UniqueConstraint("workspace_id", "email", name="uq_app_user_ws_email"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    created_at: Mapped[datetime] = _created()


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (Index("ix_account_ws_name", "workspace_id", "name"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(253))
    industry: Mapped[str | None] = mapped_column(String(100))
    segment: Mapped[str | None] = mapped_column(String(16))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    region: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(2))
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    external_ref: Mapped[str | None] = mapped_column(String(200))
    # M2a: the company (legal entity / group) this account belongs to; several accounts
    # (subsidiaries, branches, business units) can share one company.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("company.id", ondelete="SET NULL"), index=True
    )
    # M5: the rep who owns the account (Dynamics-style); a rep also sees accounts they own a
    # deal on. Backfilled from the owner of the account's most recent deal.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Contact(Base):
    """Third-party person: strict minimum (name, title, company, source). No email / phone."""

    __tablename__ = "contact"
    __table_args__ = (
        Index("ix_contact_account", "account_id"),
        CheckConstraint("reports_to_id IS NULL OR reports_to_id <> id", name="ck_contact_not_self"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    title_function: Mapped[str | None] = mapped_column(String(16))  # JobFunction, filled in M2
    title_seniority: Mapped[str | None] = mapped_column(String(16))  # Seniority, filled in M2
    title_source: Mapped[str | None] = mapped_column(String(16))  # TitleSource (M2b)
    title_flag: Mapped[str | None] = mapped_column(Text)  # why it needs a look (M2b), else None
    reports_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contact.id", ondelete="SET NULL")
    )
    # M2b: set when the manager link was validated from a rule / meeting proposal (its evidence
    # stays viewable); None for a link entered by hand.
    reports_to_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "org_proposal.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_contact_reports_to_proposal",
        )
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    source_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Deal(Base):
    __tablename__ = "deal"
    __table_args__ = (
        Index("ix_deal_ws_stage", "workspace_id", "stage"),
        Index("ix_deal_account", "account_id"),
        CheckConstraint(
            "closed_on IS NULL OR closed_on >= created_on", name="ck_deal_closed_after_created"
        ),
        CheckConstraint("amount_eur IS NULL OR amount_eur >= 0", name="ck_deal_amount_positive"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    amount_eur: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default="prospecting")
    lead_source: Mapped[str | None] = mapped_column(String(16))
    created_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Realistic data: a closed deal can miss its close date; the engine counts and excludes it.
    closed_on: Mapped[date | None] = mapped_column(Date)
    lost_reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Note(Base):
    """Free-text note on a CONTACT. Append-only (DB trigger)."""

    __tablename__ = "note"
    __table_args__ = (
        Index("ix_note_contact", "contact_id", "created_at"),
        # A version is corrected at most once: chains stay linear even under concurrent edits.
        Index(
            "uq_note_corrects",
            "corrects_id",
            unique=True,
            postgresql_where=text("corrects_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contact.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    corrects_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("note.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )


class Comment(Base):
    """Free-text comment on an ACCOUNT. Append-only (DB trigger)."""

    __tablename__ = "comment"
    __table_args__ = (
        Index("ix_comment_account", "account_id", "created_at"),
        Index(
            "uq_comment_corrects",
            "corrects_id",
            unique=True,
            postgresql_where=text("corrects_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    corrects_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comment.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = _created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )


class Run(Base):
    """History of generator runs and analysis scans (admin view later). `result` holds the
    JSON of the produced report (e.g. a ScanReport) so a result can be re-read and cited."""

    __tablename__ = "run"

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


class LlmCall(Base):
    """One row per LLM / embedding call: usage per provider for the admin view and budgets."""

    __tablename__ = "llm_call"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Usage is read per workspace (a client must never see another client's usage).
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("run.id", ondelete="SET NULL"))
    # Who caused the call; NULL = the system (background jobs, CLI) or a deleted account.
    user_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


# --- M1b: connectors and enriched contact channels ----------------------------------------------
class ConnectorCredential(Base):
    """A workspace's OAuth connection to an external MCP server (TamTam). Tokens and any client
    secret are sealed (Fernet, DATAFORCE_SECRET_KEY): they never leave the backend, never reach
    the browser and are never logged."""

    __tablename__ = "connector_credential"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider", name="uq_connector_credential_ws_provider"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # "tamtam"
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="connected")
    issuer: Mapped[str] = mapped_column(Text, nullable=False)  # authorization server origin
    resource: Mapped[str] = mapped_column(Text, nullable=False)  # the MCP URL (RFC 8707)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)  # from dynamic registration
    client_secret_enc: Mapped[str | None] = mapped_column(Text)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scope: Mapped[str | None] = mapped_column(Text)
    # Last tool list seen on the server (names, sanitised descriptions, annotations). No secrets.
    tools: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)  # sanitised, never holds a token
    connected_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class OAuthPending(Base):
    """An authorization in flight, between the "Connect" click and the callback. Single use and
    short-lived: the callback deletes it; rows past `expires_at` are refused and purged. Only a
    SHA-256 of the `state` and of the browser-binding cookie is stored."""

    __tablename__ = "oauth_pending"

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    browser_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_verifier_enc: Mapped[str] = mapped_column(Text, nullable=False)
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_secret_enc: Mapped[str | None] = mapped_column(Text)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContactChannel(Base):
    """An email / mobile of a contact, obtained only by an explicit (possibly paid) enrichment
    click. The value is sealed at rest; one click deletes it, and erasing the contact cascades.
    Kept apart from `contact`, which stays at the strict minimum."""

    __tablename__ = "contact_channel"
    __table_args__ = (Index("ix_contact_channel_contact", "contact_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contact.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # ChannelKind
    value_enc: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # "tamtam_mcp" | "fake"
    credits_used: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=0)
    raw_tool: Mapped[str | None] = mapped_column(String(200))
    fetched_at: Mapped[datetime] = _created()


# --- M2a: companies, analysis flows and their data, AI model credentials -------------------------
class Company(Base):
    """A company (legal entity or group) one or more accounts belong to. Registry data (SIREN,
    head-office address, activity code, size bracket) is business data; the registry's list of
    managers (personal data) is never stored."""

    __tablename__ = "company"
    __table_args__ = (
        Index("ix_company_ws_name", "workspace_id", "name"),
        Index(
            "uq_company_ws_siren",
            "workspace_id",
            "siren",
            unique=True,
            postgresql_where=text("siren IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    siren: Mapped[str | None] = mapped_column(String(9))  # French company id (9 digits)
    domain: Mapped[str | None] = mapped_column(String(253))
    address_line: Mapped[str | None] = mapped_column(Text)
    postal_code: Mapped[str | None] = mapped_column(String(16))
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(2))
    naf_code: Mapped[str | None] = mapped_column(String(10))  # activity code (APE/NAF)
    legal_category: Mapped[str | None] = mapped_column(String(10))  # registry nature_juridique
    size_bracket: Mapped[str | None] = mapped_column(String(8))  # registry tranche_effectif code
    category: Mapped[str | None] = mapped_column(String(8))  # PME / ETI / GE
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    registry_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class UploadedFile(Base):
    """A CSV / Excel file uploaded for analysis flows. Stored in the database (bytea) so it is
    backed up and erased with its workspace; size is capped by settings.upload_max_bytes."""

    __tablename__ = "uploaded_file"
    __table_args__ = (Index("ix_uploaded_file_ws", "workspace_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)  # sanitised original file name
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sheet: Mapped[str | None] = mapped_column(Text)  # Excel: the sheet that was read
    n_rows: Mapped[int | None] = mapped_column(Integer)
    columns: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)  # [{name, dtype}]
    created_at: Mapped[datetime] = _created()


class DataConnection(Base):
    """A read-only connection to an external PostgreSQL database for analysis flows. The
    password is sealed (Fernet); queries run in READ ONLY transactions with a timeout."""

    __tablename__ = "data_connection"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_data_connection_ws_name"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="postgres")
    host: Mapped[str] = mapped_column(String(253), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=5432)
    database: Mapped[str] = mapped_column(String(128), nullable=False)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    password_enc: Mapped[str | None] = mapped_column(Text)
    sslmode: Mapped[str] = mapped_column(String(16), nullable=False, default="require")
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_error: Mapped[str | None] = mapped_column(Text)  # sanitised, never holds the password
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Flow(Base):
    """An analysis flow: a graph of blocks (docs/M2A-CONTRACT.md section 3). Results are computed
    on demand and not stored here (a run is recorded in `run`)."""

    __tablename__ = "flow"
    __table_args__ = (Index("ix_flow_ws_name", "workspace_id", "name"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class LlmCredential(Base):
    """The workspace's AI model (Gemini or Anthropic) and its API key, entered in Settings. The
    key is sealed (Fernet), never returned to the browser, never logged."""

    __tablename__ = "llm_credential"
    __table_args__ = (UniqueConstraint("workspace_id", name="uq_llm_credential_ws"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    provider: Mapped[str] = mapped_column(String(16), nullable=False)  # "gemini" | "anthropic"
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    api_key_enc: Mapped[str] = mapped_column(Text, nullable=False)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_error: Mapped[str | None] = mapped_column(Text)  # sanitised, never holds the key
    # Opt-in: the AI may read candidate sentences of meeting transcripts for org statements.
    allow_meeting_org: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


# --- M2b: titles, org-chart proposals, transcripts and themes ------------------------------------
class TitleCache(Base):
    """An unknown title classified once by the AI, per workspace (the normalised title text is
    the key). Reused by every later run; shown flagged until a user confirms or overrides."""

    __tablename__ = "title_cache"
    __table_args__ = (
        UniqueConstraint("workspace_id", "normalized_title", name="uq_title_cache_ws_title"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    normalized_title: Mapped[str] = mapped_column(Text, nullable=False)
    function: Mapped[str] = mapped_column(String(16), nullable=False)
    seniority: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[str] = mapped_column(String(8), nullable=False)  # low | medium | high
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _created()


class OrgProposal(Base):
    """A suggested org-chart fact, never shown as fact until a user accepts it. kind reports_to:
    `manager_id` is the proposed manager (None when ambiguous: `candidates` lists them). kinds
    champion / blocker / decision_maker are signals about `contact_id` from a meeting."""

    __tablename__ = "org_proposal"
    __table_args__ = (
        Index("ix_org_proposal_account", "account_id", "status"),
        Index("ix_org_proposal_contact", "contact_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contact.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # ProposalKind
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contact.id", ondelete="CASCADE")
    )
    origin: Mapped[str] = mapped_column(String(16), nullable=False)  # ProposalOrigin
    rule: Mapped[str | None] = mapped_column(String(64))  # rule id (origin rule) or pattern id
    # rule: {"contact_title", "manager_title", "explanation"}; meeting: {"document_id",
    # "chunk_id", "excerpt", "speaker", "char_start", "char_end"} (the excerpt is exact text).
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    candidates: Mapped[list[str] | None] = mapped_column(JSONB)  # contact ids when ambiguous
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="proposed")
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("run.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )


class Document(Base):
    """An imported meeting transcript (PDF / Markdown / text) attached to an account. Only the
    extracted text is kept (sanitised); the original file is not stored."""

    __tablename__ = "document"
    __table_args__ = (Index("ix_document_account", "account_id", "meeting_date"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    # The deal the meeting was about, when known: lets flows relate themes to deal outcomes.
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("deal.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="transcript")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    meeting_date: Mapped[date | None] = mapped_column(Date)
    file_name: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    n_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str | None] = mapped_column(String(8))  # fr | en | mixed
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class DocumentChunk(Base):
    """A speaker turn (or a slice of a long one). `char_start` / `char_end` index the parent
    document's text, so every excerpt can be shown in context and verified."""

    __tablename__ = "document_chunk"
    __table_args__ = (Index("ix_document_chunk_document", "document_id", "seq"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str | None] = mapped_column(Text)  # as written in the transcript
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contact.id", ondelete="SET NULL")
    )  # the account contact the speaker was matched to
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )  # or our own rep
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class Theme(Base):
    """A theme found by code (TF-IDF + NMF over transcript chunks) in one analysis run. `label`
    and `description` come from the AI (named_by llm) or from the top terms (named_by keywords).
    Counts are computed by code."""

    __tablename__ = "theme"
    __table_args__ = (Index("ix_theme_run", "run_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("run.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="other")  # ThemeKind
    named_by: Mapped[str] = mapped_column(String(16), nullable=False)  # llm | keywords
    top_terms: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    n_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    n_documents: Mapped[int] = mapped_column(Integer, nullable=False)
    n_accounts: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = _created()


class ThemeAssignment(Base):
    __tablename__ = "theme_assignment"
    __table_args__ = (Index("ix_theme_assignment_chunk", "chunk_id"),)

    theme_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("theme.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunk.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    weight: Mapped[float] = mapped_column(Float, nullable=False)


class MeetingOrgAiCache(Base):
    """Verified AI findings for one transcript, per (text hash, provider, model): a rerun sends
    nothing again. Deleted with the document (FK cascade) and when an account contact is erased."""

    __tablename__ = "meeting_org_ai_cache"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "text_sha256", "provider", "model", name="uq_meeting_org_ai_cache"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    )
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created()


# --- M4: activities, stage history, tasks, workbooks, saved models (migration 0009_m4) -----------
class DealStageEvent(Base):
    """One stage change of a deal (docs/M4-ANALYTICS-CONTRACT.md): the history the velocity index
    needs. Written when a rep sets the stage; demo data carries a synthetic history."""

    __tablename__ = "deal_stage_event"
    __table_args__ = (
        Index("ix_deal_stage_event_deal", "deal_id", "changed_at"),
        Index("ix_deal_stage_event_ws", "workspace_id"),
        CheckConstraint(
            "source IN ('manual','import','demo','system')", name="ck_deal_stage_event_source"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    deal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("deal.id", ondelete="CASCADE"), nullable=False
    )
    from_stage: Mapped[str | None] = mapped_column(String(16))
    to_stage: Mapped[str] = mapped_column(String(16), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    created_at: Mapped[datetime] = _created()


class Activity(Base):
    """A call, email or meeting logged on an account (and optionally a deal): by hand, from a
    connected mailbox (phase 2), an import, or demo data."""

    __tablename__ = "activity"
    __table_args__ = (
        Index("ix_activity_account_time", "account_id", "occurred_at"),
        Index("ix_activity_ws_time", "workspace_id", "occurred_at"),
        CheckConstraint("kind IN ('call','email','meeting','other')", name="ck_activity_kind"),
        CheckConstraint(
            "direction IS NULL OR direction IN ('inbound','outbound')", name="ck_activity_direction"
        ),
        CheckConstraint(
            "source IN ('manual','mailbox','import','demo')", name="ck_activity_source"
        ),
        UniqueConstraint("workspace_id", "source", "external_ref", name="uq_activity_external"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), nullable=False
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deal.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[str | None] = mapped_column(String(16))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)  # capped at 10,000 characters by the service
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    external_ref: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class ActivityParticipant(Base):
    """Who took part in an activity. Erasing a contact removes the link (cascade)."""

    __tablename__ = "activity_participant"
    __table_args__ = (Index("ix_activity_participant_contact", "contact_id"),)

    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activity.id", ondelete="CASCADE"), primary_key=True
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contact.id", ondelete="CASCADE"), primary_key=True
    )


class Task(Base):
    """A to-do on a deal or account. `ai_suggested` tasks carry their source sentence in
    `evidence` and stay suggestions until a person accepts them (status open)."""

    __tablename__ = "task"
    __table_args__ = (
        Index("ix_task_ws_status", "workspace_id", "status"),
        CheckConstraint(
            "status IN ('suggested','open','in_progress','done','dismissed')", name="ck_task_status"
        ),
        CheckConstraint("source IN ('manual','ai_suggested','demo')", name="ck_task_source"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE")
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deal.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    due_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Workbook(Base):
    """A visual workbook (Oracle-DV style): canvases of visualizations as a JSON spec."""

    __tablename__ = "workbook"
    __table_args__ = (Index("ix_workbook_ws", "workspace_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class SavedModel(Base):
    """A trained model kept as plain parameters (never pickle) so the scoring block can apply it
    to new rows. `status` is the verdict against the baseline on held-out data."""

    __tablename__ = "saved_model"
    __table_args__ = (
        Index("ix_saved_model_ws", "workspace_id"),
        CheckConstraint(
            "kind IN ('linear','logistic','svm','svr','kmeans')", name="ck_saved_model_kind"
        ),
        CheckConstraint(
            "status IN ('verified','not_verified','exploratory')", name="ck_saved_model_status"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    flow_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("flow.id", ondelete="SET NULL"))
    node_id: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    features: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


# --- M4 phase 2: mailbox (Gmail, Outlook) -------------------------------------------------------
class MailboxConnection(Base):
    """A workspace's read-only link to one mailbox. The OAuth client secret, the tokens and the
    account address are sealed (Fernet): the address is needed in clear only in process, to tell
    sent from received mail and to show it to its owner, so it is sealed rather than hashed."""

    __tablename__ = "mailbox_connection"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider", name="uq_mailbox_connection_ws_provider"),
        CheckConstraint("provider IN ('gmail','outlook')", name="ck_mailbox_connection_provider"),
        CheckConstraint(
            "status IN ('configured','connected','needs_reconnect')",
            name="ck_mailbox_connection_status",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="configured")
    client_id: Mapped[str | None] = mapped_column(Text)
    client_secret_enc: Mapped[str | None] = mapped_column(Text)
    account_email_enc: Mapped[str | None] = mapped_column(Text)
    access_token_enc: Mapped[str | None] = mapped_column(Text)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)  # a fixed message, never a token
    created_at: Mapped[datetime] = _created()


class MailboxMessage(Base):
    """An email metadata record kept only because a participant is a known contact or the
    domain of an account. No body: it is fetched when a person links the email to a deal."""

    __tablename__ = "mailbox_message"
    __table_args__ = (
        UniqueConstraint("connection_id", "provider_message_id", name="uq_mailbox_message_ref"),
        Index("ix_mailbox_message_ws_deal", "workspace_id", "suggested_deal_id"),
        CheckConstraint(
            "state IN ('suggested','linked','ignored')", name="ck_mailbox_message_state"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mailbox_connection.id", ondelete="CASCADE"), nullable=False
    )
    provider_message_id: Mapped[str] = mapped_column(String(300), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(300))
    from_addr: Mapped[str] = mapped_column(String(320), nullable=False)
    to_addrs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    cc_addrs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    snippet: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    suggested_deal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("deal.id", ondelete="SET NULL")
    )
    score: Mapped[int | None] = mapped_column(Integer)
    reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="suggested")
    linked_activity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("activity.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


# --- M5: login, memberships, sessions (migration 0011_auth) --------------------------------------
class UserAccount(Base):
    """One person, across workspaces. `password_hash` NULL = an empty password, allowed only for
    demo workspaces on loopback (docs/M5-LOGIN-AND-UI-CONTRACT.md)."""

    __tablename__ = "user_account"
    __table_args__ = (CheckConstraint("workspace_credits >= 0", name="ck_user_account_credits"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(300))
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Workspaces this person may still create (a sign-up with a creation code gives 1).
    workspace_credits: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )


class Membership(Base):
    """A person's role in one workspace, and their CRM identity there."""

    __tablename__ = "membership"
    __table_args__ = (
        UniqueConstraint("user_account_id", "workspace_id", name="uq_membership_user_ws"),
        UniqueConstraint("workspace_id", "app_user_id", name="uq_membership_ws_app_user"),
        CheckConstraint("role IN ('admin', 'rep')", name="ck_membership_role"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = _workspace_fk()
    user_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    app_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    role: Mapped[str] = mapped_column(String(8), nullable=False, default="rep")
    see_all: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delete_own: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()


class UserSession(Base):
    """A signed-in browser. Only the SHA-256 of the cookie token is stored."""

    __tablename__ = "user_session"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(200))


# --- M6: creation codes and join tokens (migration 0013_accounts) --------------------------------
class CreationCode(Base):
    """A code the superadmin hands out so someone can sign up and create a workspace. Only the
    SHA-256 of the code is stored."""

    __tablename__ = "creation_code"
    __table_args__ = (
        CheckConstraint(
            "max_uses >= 1 AND max_uses <= 100 AND uses >= 0", name="ck_creation_code_uses"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    uses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JoinToken(Base):
    """A token a workspace admin hands out so someone can join that workspace. Only the SHA-256
    of the token is stored."""

    __tablename__ = "join_token"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'rep')", name="ck_join_token_role"),
        CheckConstraint(
            "max_uses >= 1 AND max_uses <= 50 AND uses >= 0", name="ck_join_token_uses"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(8), nullable=False, default="rep")
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    uses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when an invitation email was accepted for sending (counted for the daily caps).
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Performance indexes (migration 0008_indexes): `workspace_id` on the big tables, and every foreign
# key with ON DELETE CASCADE / SET NULL, so a parent delete does not scan the child table. The
# nullable ones are partial (`IS NOT NULL`): most rows hold NULL.
def _not_null(column: str) -> Any:
    return text(f"{column} IS NOT NULL")


Index("ix_contact_ws_name", Contact.workspace_id, Contact.full_name, Contact.id)
Index("ix_document_ws_date", Document.workspace_id, Document.meeting_date)
Index("ix_document_chunk_ws", DocumentChunk.workspace_id)
Index("ix_run_ws_kind_started", Run.workspace_id, Run.kind, Run.started_at.desc())
Index("ix_comment_ws", Comment.workspace_id)
Index("ix_contact_channel_ws", ContactChannel.workspace_id)
Index("ix_note_ws", Note.workspace_id)
Index("ix_meeting_org_ai_cache_ws", MeetingOrgAiCache.workspace_id)
Index("ix_oauth_pending_ws", OAuthPending.workspace_id)
Index("ix_org_proposal_ws", OrgProposal.workspace_id)
Index("ix_theme_ws", Theme.workspace_id)
Index("ix_theme_assignment_ws", ThemeAssignment.workspace_id)
for _idx, _col in (
    ("ix_deal_stage_event_changed_by", DealStageEvent.changed_by_id),
    ("ix_activity_deal", Activity.deal_id),
    ("ix_activity_author", Activity.author_user_id),
    ("ix_task_account", Task.account_id),
    ("ix_task_deal", Task.deal_id),
    ("ix_task_owner", Task.owner_user_id),
    ("ix_workbook_created_by", Workbook.created_by_id),
    ("ix_saved_model_flow", SavedModel.flow_id),
    ("ix_saved_model_created_by", SavedModel.created_by_id),
    ("ix_comment_author", Comment.author_id),
    ("ix_comment_deleted_by", Comment.deleted_by_id),
    ("ix_contact_reports_to", Contact.reports_to_id),
    ("ix_contact_reports_to_proposal", Contact.reports_to_proposal_id),
    ("ix_deal_owner", Deal.owner_id),
    ("ix_document_created_by", Document.created_by_id),
    ("ix_document_chunk_contact", DocumentChunk.contact_id),
    ("ix_document_chunk_user", DocumentChunk.user_id),
    ("ix_llm_call_run", LlmCall.run_id),
    ("ix_note_author", Note.author_id),
    ("ix_note_deleted_by", Note.deleted_by_id),
    ("ix_org_proposal_decided_by", OrgProposal.decided_by_id),
    ("ix_org_proposal_manager", OrgProposal.manager_id),
    ("ix_org_proposal_run", OrgProposal.run_id),
    ("ix_account_owner", Account.owner_id),
    ("ix_membership_app_user", Membership.app_user_id),
):
    Index(_idx, _col, postgresql_where=_not_null(_col.key))
Index(
    "ix_mailbox_message_activity",
    MailboxMessage.linked_activity_id,
    postgresql_where=_not_null("linked_activity_id"),
)
Index(
    "ix_mailbox_message_deal",
    MailboxMessage.suggested_deal_id,
    postgresql_where=_not_null("suggested_deal_id"),
)


# --- M6: admin-editable limits and AI prices ----------------------------------------------------
class SettingOverride(Base):
    """An admin-set value for an allow-listed limit (app/services/limits.py). `workspace_id`
    NULL = global. The effective value is the workspace override, else the global one, else the
    `.env` default."""

    __tablename__ = "setting_override"
    __table_args__ = (
        Index(
            "uq_setting_override_ws",
            "key",
            "workspace_id",
            unique=True,
            postgresql_where=text("workspace_id IS NOT NULL"),
        ),
        Index(
            "uq_setting_override_global",
            "key",
            unique=True,
            postgresql_where=text("workspace_id IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE")
    )
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = _updated()


class SettingOverrideAudit(Base):
    """Append-only trail of limit changes: who, when, old to new (NULL = the default)."""

    __tablename__ = "setting_override_audit"

    id: Mapped[uuid.UUID] = _uuid_pk()
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE")
    )
    old_value: Mapped[Any | None] = mapped_column(JSONB)
    new_value: Mapped[Any | None] = mapped_column(JSONB)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    changed_at: Mapped[datetime] = _created()


class ModelPrice(Base):
    """What one million tokens of a model cost, set by the superadmin. No row = no price: the
    usage page then says "set a price" instead of guessing."""

    __tablename__ = "model_price"
    __table_args__ = (UniqueConstraint("provider", "model", name="uq_model_price"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    input_per_mtok_eur: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    output_per_mtok_eur: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = _updated()
