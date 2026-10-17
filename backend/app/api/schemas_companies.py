"""HTTP contract of companies and the public registry (M2a, agent G)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas import AccountOut, ContactOut, DealOut, _In


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    siren: str | None = None
    domain: str | None = None
    address_line: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None
    naf_code: str | None = None
    legal_category: str | None = None
    size_bracket: str | None = None
    category: str | None = None
    source: str
    registry_checked_at: datetime | None = None
    created_at: datetime
    n_accounts: int = 0
    n_contacts: int = 0
    n_deals: int = 0
    n_open_deals: int = 0
    won_amount_eur: Decimal = Decimal(0)
    last_interaction: date | None = None
    interacted: bool = False


class CompanyCreate(_In):
    name: str = Field(min_length=1, max_length=300)
    siren: str | None = Field(default=None, pattern=r"^[0-9]{9}$")
    domain: str | None = Field(default=None, max_length=253)
    address_line: str | None = Field(default=None, max_length=500)
    postal_code: str | None = Field(default=None, max_length=16)
    city: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, min_length=2, max_length=2)


class CompanyUpdate(_In):
    """Partial; an explicit null clears a field (except `name`)."""

    name: str | None = Field(default=None, min_length=1, max_length=300)
    domain: str | None = Field(default=None, max_length=253)
    address_line: str | None = Field(default=None, max_length=500)
    postal_code: str | None = Field(default=None, max_length=16)
    city: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, min_length=2, max_length=2)


class LookupOut(BaseModel):
    companies: list[CompanyOut]
    accounts: list[AccountOut]  # matching accounts that belong to no company
    interacted: bool


class AccountCompanyLink(_In):
    company_id: UUID | None  # null unlinks


class RegistryCompanyOut(BaseModel):
    siren: str
    name: str
    address_line: str | None
    postal_code: str | None
    city: str | None
    naf_code: str | None
    legal_category: str | None
    size_bracket: str | None
    category: str | None
    created_on: date | None
    active: bool
    sole_trader: bool
    protected: bool = False
    in_crm_company_id: UUID | None


class RegistrySearchIn(_In):
    q: str = Field(min_length=1, max_length=100)  # registry.MAX_QUERY_CHARS


class FromRegistry(_In):
    siren: str = Field(pattern=r"^[0-9]{9}$")
    create_account: bool = False


class ActivityItem(BaseModel):
    kind: Literal["note", "comment", "deal_created", "deal_closed"]
    at: datetime | date
    account_id: UUID
    contact_id: UUID | None = None
    deal_id: UUID | None = None
    title: str
    excerpt: str | None = None


class Company360(BaseModel):
    company: CompanyOut
    accounts: list[AccountOut]
    contacts: list[ContactOut]  # at most 200
    deals: list[DealOut]  # at most 500
    activity: list[ActivityItem]  # newest first, at most 50
