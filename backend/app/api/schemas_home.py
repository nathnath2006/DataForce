"""HTTP contract of the Home dashboard."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class HomeKpis(BaseModel):
    open_deals: int
    open_pipeline_eur: Decimal  # sum of the amounts of open deals (a missing amount counts 0)
    won_this_quarter: int  # deals closed won since the first day of this calendar quarter
    won_this_quarter_eur: Decimal
    tasks_due_week: int  # open tasks due from today to Sunday
    tasks_overdue: int  # open tasks due before today


class HomeDeal(BaseModel):
    id: UUID
    name: str
    account_id: UUID
    account_name: str
    stage: str
    amount_eur: Decimal | None
    created_on: date
    owner_name: str | None


class HomeStage(BaseModel):
    stage: str
    count: int  # exact count of visible deals in that stage
    amount_eur: Decimal  # sum of their amounts (a missing amount counts 0)


class HomeStalledDeal(HomeDeal):
    days_in_stage: int  # days since the last stage change (or since creation)


class HomeTask(BaseModel):
    id: UUID
    title: str
    due_on: date | None
    status: str
    overdue: bool
    deal_id: UUID | None
    deal_name: str | None
    account_id: UUID | None
    account_name: str | None


class HomeActivity(BaseModel):
    id: str
    kind: str
    at: datetime
    title: str
    author_name: str | None
    deal_id: UUID
    deal_name: str


class HomeOut(BaseModel):
    kpis: HomeKpis
    open_deals: list[HomeDeal]  # the newest open deals
    top_deals: list[HomeDeal] = []  # the biggest open deals
    stalled_deals: list[HomeStalledDeal] = []  # open, no stage change for STALL_DAYS or more
    stalled_total: int = 0  # how many such deals in all (the list shows the oldest few)
    by_stage: list[HomeStage] = []  # every stage, in pipeline order
    tasks: list[HomeTask]
    activity: list[HomeActivity]
