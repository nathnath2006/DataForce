"""Admin-editable limits: a fixed allow-list, each key with type, bounds, unit and `.env` default.

`effective(db, settings, key, ws_id)` is the one way a service reads a limit: the workspace
override, else the global override, else the `.env` default. All overrides are read in one small
query and kept in a short in-process cache (TTL below), invalidated on every write; with several
server processes the others catch up within the TTL. Never add a secret, URL, key or password.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import SettingOverride, SettingOverrideAudit
from app.services.errors import InvalidInputError, NotFoundError

CACHE_TTL_S = 10.0


@dataclass(frozen=True)
class LimitDef:
    key: str
    kind: str  # "int" | "float"
    minimum: float
    maximum: float
    unit: str
    description: str
    group: str


def _d(key, kind, lo, hi, unit, description, group) -> LimitDef:
    return LimitDef(key, kind, lo, hi, unit, description, group)


# Bounds mirror the hard limits of app/config.py, so an override can never exceed what the
# application was built to tolerate.
LIMITS: tuple[LimitDef, ...] = (
    _d(
        "titles_max_llm_calls_per_run",
        "int",
        0,
        5_000,
        "calls",
        "AI calls for title normalisation, per run",
        "AI",
    ),
    _d(
        "titles_max_llm_calls_per_day",
        "int",
        0,
        50_000,
        "calls/day",
        "AI calls for title normalisation, per day",
        "AI",
    ),
    _d(
        "org_ai_max_calls_per_run",
        "int",
        0,
        5_000,
        "calls",
        "AI calls for org-chart proposals, per run",
        "AI",
    ),
    _d(
        "org_ai_max_calls_per_day",
        "int",
        0,
        50_000,
        "calls/day",
        "AI calls for org-chart proposals, per day",
        "AI",
    ),
    _d(
        "genai_max_calls_per_day",
        "int",
        0,
        50_000,
        "calls/day",
        "AI calls for deal summaries and action items, per day",
        "AI",
    ),
    _d(
        "genai_max_source_chars",
        "int",
        1_000,
        200_000,
        "characters",
        "Maximum source text sent for a summary or action items",
        "AI",
    ),
    _d(
        "assistant_max_asks_per_hour",
        "int",
        1,
        10_000,
        "questions/hour",
        "Assistant questions per hour",
        "Assistant",
    ),
    _d(
        "assistant_max_context_chars",
        "int",
        2_000,
        400_000,
        "characters",
        "Assistant: maximum context sent to the model",
        "Assistant",
    ),
    _d(
        "assistant_max_output_tokens",
        "int",
        64,
        4_096,
        "tokens",
        "Assistant: maximum answer length",
        "Assistant",
    ),
    _d(
        "mailbox_lookback_days",
        "int",
        1,
        365,
        "days",
        "Mailbox sync: how far back headers are read",
        "Mailbox",
    ),
    _d(
        "mailbox_max_messages",
        "int",
        1,
        5_000,
        "messages",
        "Mailbox sync: maximum headers read per sync",
        "Mailbox",
    ),
    _d(
        "mailbox_suggest_threshold",
        "int",
        1,
        100,
        "points",
        "Mailbox: minimum score to suggest a deal",
        "Mailbox",
    ),
    _d(
        "flow_max_rows",
        "int",
        1_000,
        5_000_000,
        "rows",
        "Analysis: maximum rows per dataset or block",
        "Analysis",
    ),
    _d("flow_run_timeout_s", "float", 1, 600, "seconds", "Analysis: flow run timeout", "Analysis"),
    _d(
        "db_quota_mb",
        "int",
        1,
        10_000_000,
        "MB",
        "Storage quota shown in the admin view",
        "Storage",
    ),
)
# A minimum-type limit: a workspace "lowering" it would loosen it, so only the superadmin sets it.
GLOBAL_ONLY: frozenset[str] = frozenset({"mailbox_suggest_threshold"})
BY_KEY: dict[str, LimitDef] = {d.key: d for d in LIMITS}

_lock = threading.Lock()
_cache: tuple[float, dict[tuple[str, uuid.UUID | None], Any]] | None = None


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def _snapshot(db: Session) -> dict[tuple[str, uuid.UUID | None], Any]:
    global _cache
    now = time.monotonic()
    with _lock:
        if _cache is not None and now - _cache[0] < CACHE_TTL_S:
            return _cache[1]
    rows = db.execute(
        select(SettingOverride.key, SettingOverride.workspace_id, SettingOverride.value)
    )
    data = {(k, w): v for k, w, v in rows}
    with _lock:
        _cache = (now, data)
    return data


def default_of(settings: Settings, key: str) -> Any:
    return getattr(settings, key)


def resolve(db: Session, settings: Settings, key: str, ws_id: uuid.UUID | None) -> tuple[Any, str]:
    """(value, source) with source in "workspace", "global", "default". A workspace value never
    exceeds the global one, even if the global was lowered after the workspace was set."""
    if key not in BY_KEY:
        raise NotFoundError("unknown limit")
    snap = _snapshot(db)
    if (key, None) in snap:
        ceiling, ceiling_source = snap[(key, None)], "global"
    else:
        ceiling, ceiling_source = default_of(settings, key), "default"
    own = snap.get((key, ws_id)) if ws_id is not None and key not in GLOBAL_ONLY else None
    if own is not None and own <= ceiling:
        return own, "workspace"
    return ceiling, ceiling_source


def effective(db: Session, settings: Settings, key: str, ws_id: uuid.UUID | None) -> Any:
    return resolve(db, settings, key, ws_id)[0]


def effective_settings(db: Session, settings: Settings, ws_id: uuid.UUID | None) -> Settings:
    """A copy of `settings` with every override applied, for code that threads a Settings."""
    update = {
        key: value
        for key in BY_KEY
        for value, source in [resolve(db, settings, key, ws_id)]
        if source != "default"
    }
    return settings.model_copy(update=update) if update else settings


def validate(key: str, value: Any) -> int | float:
    d = BY_KEY.get(key)
    if d is None:
        raise NotFoundError("unknown limit")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidInputError("the value must be a number")
    if d.kind == "int":
        if isinstance(value, float) and not value.is_integer():
            raise InvalidInputError(f"{key} must be a whole number")
        value = int(value)
    else:
        value = float(value)
        if value != value or value in (float("inf"), float("-inf")):
            raise InvalidInputError("the value must be a finite number")
    if not d.minimum <= value <= d.maximum:
        raise InvalidInputError(f"{key} must be between {d.minimum:g} and {d.maximum:g} {d.unit}")
    return value


def _insert_or_update(
    db: Session, key: str, ws_id: uuid.UUID | None, value: Any, user_id: uuid.UUID | None
) -> None:
    """Two first writes at once must not hit the unique index: the loser updates instead."""
    existing = db.scalar(
        select(SettingOverride).where(
            SettingOverride.key == key,
            SettingOverride.workspace_id.is_(None)
            if ws_id is None
            else SettingOverride.workspace_id == ws_id,
        )
    )
    if existing is not None:
        existing.value, existing.updated_by = value, user_id
        return
    try:
        with db.begin_nested():
            db.add(SettingOverride(key=key, workspace_id=ws_id, value=value, updated_by=user_id))
            db.flush()
    except IntegrityError:
        db.execute(
            update(SettingOverride)
            .where(
                SettingOverride.key == key,
                SettingOverride.workspace_id.is_(None)
                if ws_id is None
                else SettingOverride.workspace_id == ws_id,
            )
            .values(value=value, updated_by=user_id)
        )


def set_override(
    db: Session,
    key: str,
    ws_id: uuid.UUID | None,
    value: Any | None,
    user_id: uuid.UUID | None,
    settings: Settings | None = None,
) -> None:
    """Set the override (`value` None = remove it, back to the default) and audit the change.
    Runs in the caller's transaction; the caller commits. With `settings`, a workspace value is
    checked against the global one (lower or equal only)."""
    clean = None if value is None else validate(key, value)
    if value is None and key not in BY_KEY:
        raise NotFoundError("unknown limit")
    if ws_id is not None and key in GLOBAL_ONLY:
        raise InvalidInputError("this limit is global only")
    if clean is not None and ws_id is not None:
        # A workspace may only tighten the global value, never loosen it.
        ceiling = effective(db, settings, key, None) if settings is not None else None
        if ceiling is not None and clean > ceiling:
            raise InvalidInputError(f"{key} cannot be higher than the global value ({ceiling:g})")
    cond = [SettingOverride.key == key]
    cond.append(
        SettingOverride.workspace_id.is_(None)
        if ws_id is None
        else SettingOverride.workspace_id == ws_id
    )
    row = db.scalar(select(SettingOverride).where(*cond))
    old = row.value if row is not None else None
    if clean is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        _insert_or_update(db, key, ws_id, clean, user_id)
    else:
        row.value, row.updated_by = clean, user_id
    db.add(
        SettingOverrideAudit(
            key=key, workspace_id=ws_id, old_value=old, new_value=clean, changed_by=user_id
        )
    )
    db.flush()
    invalidate()
