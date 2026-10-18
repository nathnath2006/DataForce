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

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # ConnectorProvider
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
