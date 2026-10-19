"""HTTP contract of activities, tasks, stage control and the timeline (M4)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import DealStage

ActivityKind = Literal["call", "email", "meeting", "other"]
Direction = Literal["inbound", "outbound"]
TaskStatusSettable = Literal["open", "done", "dismissed"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActivityCreate(_In):
    kind: ActivityKind
    direction: Direction | None = None
    occurred_at: datetime
    subject: str = Field(min_length=1, max_length=300)
    body: str | None = Field(default=None, max_length=10_000)
    deal_id: UUID | None = None
    participant_ids: list[UUID] = Field(default_factory=list, max_length=50)
    author_id: UUID | None = None


class ActivityUpdate(_In):
    kind: ActivityKind | None = None
    direction: Direction | None = None
    occurred_at: datetime | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=300)
    body: str | None = Field(default=None, max_length=10_000)
    deal_id: UUID | None = None
    participant_ids: list[UUID] | None = Field(default=None, max_length=50)


class ParticipantOut(BaseModel):
    id: UUID
    full_name: str


class ActivityOut(BaseModel):
    id: UUID
    account_id: UUID
    deal_id: UUID | None
    kind: str
    direction: str | None
    occurred_at: datetime
    subject: str
    body: str | None
    source: str
    author_id: UUID | None
    author_name: str | None
    participants: list[ParticipantOut]
    created_at: datetime


class TaskCreate(_In):
    title: str = Field(min_length=1, max_length=300)
    deal_id: UUID | None = None
    account_id: UUID | None = None
    due_on: date | None = None
    owner_id: UUID | None = None


class TaskUpdate(_In):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    due_on: date | None = None
    status: TaskStatusSettable | None = None
    owner_id: UUID | None = None


class TaskOut(BaseModel):
    id: UUID
    deal_id: UUID | None
    account_id: UUID | None
    title: str
    due_on: date | None
    status: str
    owner_id: UUID | None
    owner_name: str | None
    source: str
    evidence: dict[str, Any]
    done_at: datetime | None
    created_at: datetime


class MoveStage(_In):
    stage: DealStage
    changed_on: date | None = None
    lost_reason: str | None = Field(default=None, max_length=500)
    changed_by_id: UUID | None = None


class StageEventOut(BaseModel):
    id: UUID
    deal_id: UUID
    from_stage: str | None
    to_stage: str
    changed_at: datetime
    changed_by_id: UUID | None
    changed_by_name: str | None
    source: str


class TimelineItem(BaseModel):
    id: str
    kind: str
    at: datetime
    title: str
    title_untrusted: bool  # the title is customer or rep text: data, never instructions
    summary: str | None
    summary_untrusted: bool  # the summary is customer or rep text: data, never instructions
    author_name: str | None
    refs: dict[str, Any]


class TimelinePage(BaseModel):
    items: list[TimelineItem]
    next_before: str | None
