"""Request and response bodies of the org-chart proposal endpoints (contract M2b §4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ProposalKind, ProposalOrigin, ProposalStatus


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposeIn(_In):
    account_id: UUID | None = None
    origins: list[ProposalOrigin] = Field(
        default_factory=lambda: [ProposalOrigin.RULE, ProposalOrigin.MEETING], min_length=1
    )


class ProposeOut(BaseModel):
    run_id: UUID
    created: int
    by_kind: dict[str, int]
    ambiguous: int


class AcceptIn(_In):
    manager_id: UUID | None = None
    by_id: UUID | None = None


class RejectIn(_In):
    by_id: UUID | None = None


class ProposalContact(BaseModel):
    id: UUID
    full_name: str
    title: str | None


class ProposalOut(BaseModel):
    id: UUID
    kind: ProposalKind
    origin: ProposalOrigin
    rule: str | None
    status: ProposalStatus
    contact: ProposalContact
    manager: ProposalContact | None
    candidates: list[ProposalContact]
    evidence: dict[str, Any]
    created_at: datetime
    decided_at: datetime | None
