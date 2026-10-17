"""Request / response models of the title endpoints (agent T)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from app.domain.enums import JobFunction, Seniority


class NormalizeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    use_ai: bool = True


class BySource(BaseModel):
    dictionary: int
    llm: int
    manual: int
    unknown: int


class NormalizeOut(BaseModel):
    run_id: uuid.UUID
    n_contacts: int
    by_source: BySource
    n_flagged: int
    llm_calls: int
    ai_configured: bool


class TitleClassIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    function: JobFunction
    seniority: Seniority


class ReviewItem(BaseModel):
    contact_id: uuid.UUID
    full_name: str
    account_id: uuid.UUID
    account_name: str
    title: str | None
    function: str
    seniority: str
    source: str  # dictionary | llm | manual | unknown
    flag: str | None


class PreviewOut(BaseModel):
    normalized: str
    function: str
    seniority: str
    source: str  # dictionary | none
    flag: str | None
    matched: bool
