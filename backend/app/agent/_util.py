"""Shared helpers of the agent tools: text safety, paging, number conversion."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.agent.errors import ToolError
from app.db.models import Account, Company
from app.llm.untrusted import sanitize_text
from app.services._common import get_scoped

EXCERPT_CHARS = 300
BODY_CHARS = 2000
NAME_CHARS = 300
_WS = re.compile(r"\s+")


def clean(text: str | None, cap: int = NAME_CHARS) -> str | None:
    """Sanitised (control chars, source-tag look-alikes) and capped. For fields of our own data
    (names, titles) that are not marked untrusted."""
    if text is None:
        return None
    return sanitize_text(text)[:cap]


def untrusted(text: str | None, cap: int = BODY_CHARS) -> str | None:
    """Free text that comes from people or files: same transform, returned in a field whose name
    ends in `_untrusted`."""
    return clean(text, cap)


def excerpt(text: str | None, cap: int = EXCERPT_CHARS) -> str | None:
    if text is None:
        return None
    t = sanitize_text(_WS.sub(" ", text).strip())
    return t if len(t) <= cap else t[: cap - 1] + "…"


def num(value: Decimal | float | int | None) -> float | None:
    return None if value is None else float(value)


def cycle_days(created: date | None, closed: date | None) -> int | None:
    if created is None or closed is None:
        return None
    return (closed - created).days


def iso(value: datetime | date | None) -> str | None:
    return None if value is None else value.isoformat()


def require_account_row(session: Session, ws_id: uuid.UUID, account_id: uuid.UUID) -> Account:
    row = get_scoped(session, Account, ws_id, account_id)
    if row is None:
        raise ToolError("account not found")
    return row


def require_company_row(session: Session, ws_id: uuid.UUID, company_id: uuid.UUID) -> Company:
    row = get_scoped(session, Company, ws_id, company_id)
    if row is None:
        raise ToolError("company not found")
    return row


def json_clean(value: Any, cap: int = 300) -> Any:
    """Recursively sanitise every string of a JSON-like value (flow previews and views)."""
    if isinstance(value, str):
        return sanitize_text(value)[:cap]
    if isinstance(value, dict):
        return {(sanitize_text(k)[:cap] if isinstance(k, str) else k): json_clean(v, cap)
                for k, v in value.items()}  # fmt: skip
    if isinstance(value, list | tuple):
        return [json_clean(v, cap) for v in value]
    return value
