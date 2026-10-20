"""Server-side sessions: a random cookie token, only its SHA-256 stored."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import UserAccount, UserSession

COOKIE = "df_session"
SLIDING = timedelta(days=14)
ABSOLUTE = timedelta(days=30)
TOUCH_EVERY = timedelta(minutes=1)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def create_session(db: Session, user: UserAccount, user_agent: str | None) -> str:
    """Store a new session and return the cookie token (shown once)."""
    token = secrets.token_urlsafe(32)
    now = _now()
    db.add(
        UserSession(
            user_account_id=user.id,
            token_hash=hash_token(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + SLIDING,
            user_agent=(user_agent or "")[:200] or None,
        )
    )
    user.last_login_at = now
    db.flush()
    return token


def resolve(db: Session, token: str | None) -> UserAccount | None:
    """The signed-in user for a cookie token, or None (unknown, expired, disabled). Slides the
    expiry (never past 30 days from creation) and updates last_seen_at at most once a minute."""
    if not token:
        return None
    row = db.scalars(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    ).one_or_none()
    if row is None:
        return None
    now = _now()
    if row.expires_at <= now or row.created_at + ABSOLUTE <= now:
        db.delete(row)
        db.commit()
        return None
    user = db.get(UserAccount, row.user_account_id)
    if user is None or user.disabled:
        return None
    if now - row.last_seen_at >= TOUCH_EVERY:
        row.last_seen_at = now
        row.expires_at = min(now + SLIDING, row.created_at + ABSOLUTE)
        db.commit()
    return user


def end_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))


def end_all_sessions(db: Session, user_id) -> None:
    db.execute(delete(UserSession).where(UserSession.user_account_id == user_id))
