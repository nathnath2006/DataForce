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
    use_ai: bool = False  # the AI pass also needs the workspace switch (Settings -> AI model)


class AiPassOut(BaseModel):
    used: bool
    calls: int
    capped: int
    failed: int
    dropped: int


class ProposeOut(BaseModel):
    run_id: UUID
    created: int
    by_kind: dict[str, int]
    ambiguous: int
    ai: AiPassOut | None = None


class AcceptIn(_In):
    manager_id: UUID | None = None
    force: bool = False  # replace a manager set since the proposal was made


class RejectIn(_In):
    pass


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
