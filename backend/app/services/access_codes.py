"""Creation codes and join tokens: random, shown once, stored as a SHA-256 hash, and counted
atomically so two sign-ups cannot use the last slot together."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import CreationCode, JoinToken
from app.services.errors import InvalidInputError

GENERIC_ERROR = "invalid or expired code"
CODE_BYTES = 24  # 32 url-safe characters, 192 bits


def new_secret() -> str:
    return secrets.token_urlsafe(CODE_BYTES)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.strip().encode("utf-8")).hexdigest()


def status_of(row: CreationCode | JoinToken, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    if row.revoked_at is not None:
        return "revoked"
    if row.expires_at <= now:
        return "expired"
    if row.uses >= row.max_uses:
        return "used_up"
    return "active"


def make_code(
    db: Session, creator: uuid.UUID, label: str, expires_in_days: int, max_uses: int
) -> tuple[CreationCode, str]:
    label = label.strip()
    if not label:
        raise InvalidInputError("the label is empty")
    code = new_secret()
    row = CreationCode(
        code_hash=hash_secret(code),
        label=label,
        created_by=creator,
        expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
        max_uses=max_uses,
        uses=0,
    )
    db.add(row)
    db.flush()
    return row, code


def make_join_token(
    db: Session,
    ws_id: uuid.UUID,
    creator: uuid.UUID,
    role: str,
    label: str,
    expires_in_days: int,
    max_uses: int,
) -> tuple[JoinToken, str]:
    label = label.strip()
    if not label:
        raise InvalidInputError("the label is empty")
    token = new_secret()
    row = JoinToken(
        workspace_id=ws_id,
        token_hash=hash_secret(token),
        role=role,
        label=label,
        created_by=creator,
        expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
        max_uses=max_uses,
        uses=0,
    )
    db.add(row)
    db.flush()
    return row, token


def _consume(db: Session, model, hash_col, secret: str):  # noqa: ANN001, ANN202
    """Count one use of the row matching `secret`, or None when it is wrong, expired, revoked or
    used up. The check and the count are one UPDATE, so the last slot goes to one caller."""
    digest = hash_secret(secret)
    row = db.scalars(select(model).where(hash_col == digest)).one_or_none()
    if row is None or not hmac.compare_digest(getattr(row, hash_col.key), digest):
        return None
    got = db.execute(
        update(model)
        .where(
            model.id == row.id,
            model.revoked_at.is_(None),
            model.expires_at > datetime.now(UTC),
            model.uses < model.max_uses,
        )
        .values(uses=model.uses + 1)
        .returning(model.id)
    ).first()
    if got is None:
        return None
    db.refresh(row)
    return row


def consume_code(db: Session, code: str) -> CreationCode | None:
    return _consume(db, CreationCode, CreationCode.code_hash, code)


def consume_join_token(db: Session, token: str) -> JoinToken | None:
    return _consume(db, JoinToken, JoinToken.token_hash, token)
