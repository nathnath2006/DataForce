"""Request and response bodies for creation codes and join tokens."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CodeStatus = Literal["active", "expired", "revoked", "used_up"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreationCodeCreate(_In):
    label: str = Field(min_length=1, max_length=200)
    expires_in_days: int = Field(default=14, ge=1, le=365)
    max_uses: int = Field(default=1, ge=1, le=100)


class CreationCodeOut(BaseModel):
    id: UUID
    label: str
    created_at: datetime
    expires_at: datetime
    max_uses: int
    uses: int
    revoked_at: datetime | None
    status: CodeStatus


class CreationCodeCreated(CreationCodeOut):
    code: str  # shown this one time only


class JoinTokenCreate(_In):
    role: Literal["rep", "admin"] = "rep"
    label: str = Field(min_length=1, max_length=200)
    expires_in_days: int = Field(default=7, ge=1, le=365)
    max_uses: int = Field(default=1, ge=1, le=50)
    email_to: str | None = Field(default=None, max_length=320, pattern=r"^[^@\s,;<>]+@[^@\s,;<>]+$")


class JoinTokenOut(BaseModel):
    id: UUID
    role: Literal["rep", "admin"]
    label: str
    created_at: datetime
    expires_at: datetime
    max_uses: int
    uses: int
    revoked_at: datetime | None
    status: CodeStatus


class JoinTokenCreated(JoinTokenOut):
    token: str  # shown this one time only
    link: str
    email_queued: bool
