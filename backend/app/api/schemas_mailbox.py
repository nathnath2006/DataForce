"""HTTP contract of the mailbox (Gmail, Outlook): connections, candidate emails, linking."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Provider = Literal["gmail", "outlook"]
MessageState = Literal["suggested", "linked", "ignored"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MailboxClientIn(_In):
    client_id: str = Field(min_length=1, max_length=512)
    client_secret: str | None = Field(default=None, max_length=2048)


class MailboxCounts(BaseModel):
    suggested: int = 0
    unmatched: int = 0
    linked: int = 0
    ignored: int = 0


class MailboxConnectionOut(BaseModel):
    provider: Provider
    label: str
    status: Literal["not_configured", "configured", "connected", "needs_reconnect"]
    client_source: Literal["settings", "env"] | None
    secret_key_configured: bool
    account_email: str | None
    redirect_uri: str
    last_sync_at: datetime | None
    last_error: str | None
    counts: MailboxCounts


class MailboxStatusOut(BaseModel):
    connections: list[MailboxConnectionOut]
    lookback_days: int
    max_messages: int


class MailboxConnectOut(BaseModel):
    authorize_url: str


class MailboxSyncIn(_In):
    provider: Provider | None = None


class MailboxSyncResultOut(BaseModel):
    run_id: UUID
    fetched: int
    candidates: int
    new: int
    suggested: int
    errors: list[str]


class MailboxMessageOut(BaseModel):
    id: UUID
    provider: Provider
    from_addr: str
    to_addrs: list[str]
    cc_addrs: list[str]
    sent_at: datetime
    subject: str
    snippet: str
    state: MessageState
    suggested_deal_id: UUID | None
    score: int | None
    reasons: list[str]
    linked_activity_id: UUID | None


class MailboxLinkIn(_In):
    deal_id: UUID
