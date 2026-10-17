"""Generator-side records: local string keys instead of database UUIDs. Pure data, no DB."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.domain.enums import DealStage, LeadSource, RecordSource
from app.domain.schemas import AccountIn, GroundTruth, UserIn


class DemoUser(UserIn):
    key: str


class DemoAccount(AccountIn):
    key: str


class DemoContact(BaseModel):
    key: str
    account_key: str
    full_name: str
    title: str | None = None
    reports_to_key: str | None = None  # the manual link loaded in the CRM (None if removed)
    role: str | None = None  # ROLE_TITLES key; ground truth only, never loaded
    source: RecordSource = RecordSource.DEMO


class DemoDeal(BaseModel):
    key: str
    account_key: str
    owner_key: str | None = None
    name: str
    amount_eur: Decimal | None = None
    stage: DealStage = DealStage.PROSPECTING
    lead_source: LeadSource | None = None
    created_on: date
    closed_on: date | None = None
    lost_reason: str | None = None
    source: RecordSource = RecordSource.DEMO


class DemoNote(BaseModel):
    """A note on a contact. `corrects_key` points to an earlier note of the dataset."""

    key: str
    contact_key: str
    author_key: str | None
    body: str
    corrects_key: str | None = None
    # When it was written (synthetic, set by the generator); None = load time.
    created_at: datetime | None = None


class DemoComment(BaseModel):
    """A comment on an account (same shape as a note, targeting an account)."""

    key: str
    account_key: str
    author_key: str | None
    body: str
    corrects_key: str | None = None
    # When it was written (synthetic, set by the generator); None = load time.
    created_at: datetime | None = None


class DemoCompany(BaseModel):
    """A company grouping demo accounts by name family. Synthetic address, never a SIREN."""

    key: str
    name: str
    address_line: str
    postal_code: str
    city: str
    country: str = "FR"
    source: RecordSource = RecordSource.DEMO


class DemoDocument(BaseModel):
    """A synthetic meeting transcript tied to a deal (`Name: text` lines)."""

    key: str
    account_key: str
    deal_key: str
    title: str
    text: str
    meeting_date: date
    language: str


class DemoDataset(BaseModel):
    users: list[DemoUser] = Field(default_factory=list)
    accounts: list[DemoAccount] = Field(default_factory=list)
    contacts: list[DemoContact] = Field(default_factory=list)
    deals: list[DemoDeal] = Field(default_factory=list)
    notes: list[DemoNote] = Field(default_factory=list)
    comments: list[DemoComment] = Field(default_factory=list)
    companies: list[DemoCompany] = Field(default_factory=list)
    documents: list[DemoDocument] = Field(default_factory=list)
    account_company: dict[str, str] = Field(default_factory=dict)  # account key -> company key
    ground_truth: GroundTruth
