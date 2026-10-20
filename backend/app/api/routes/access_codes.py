"""Creation codes (superadmin) and join tokens (workspace admin)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select, update

from app.api.deps import AdminViewer, AppSettings, CurrentWorkspace, Db, SuperAdmin
from app.api.schemas_access import (
    CreationCodeCreate,
    CreationCodeCreated,
    CreationCodeOut,
    JoinTokenCreate,
    JoinTokenCreated,
    JoinTokenOut,
)
from app.auth.demo import NotDemo
from app.config import ui_origin
from app.db.models import CreationCode, JoinToken
from app.services import access_codes, mailer
from app.services.errors import NotFoundError

router = APIRouter(tags=["access"])


def _code_out(row: CreationCode) -> dict[str, object]:
    return {
        "id": row.id,
        "label": row.label,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "max_uses": row.max_uses,
        "uses": row.uses,
        "revoked_at": row.revoked_at,
        "status": access_codes.status_of(row),
    }


def _token_out(row: JoinToken) -> dict[str, object]:
    return {**_code_out(row), "role": row.role}


@router.get("/admin/creation-codes", response_model=list[CreationCodeOut])
def list_creation_codes(db: Db, admin: SuperAdmin) -> list[CreationCodeOut]:
    rows = db.scalars(select(CreationCode).order_by(CreationCode.created_at.desc()))
    return [CreationCodeOut(**_code_out(r)) for r in rows]


@router.post(
    "/admin/creation-codes",
    response_model=CreationCodeCreated,
    status_code=201,
    dependencies=[NotDemo],
)
def create_creation_code(
    body: CreationCodeCreate, db: Db, admin: SuperAdmin
) -> CreationCodeCreated:
    row, code = access_codes.make_code(
        db, admin.id, body.label, body.expires_in_days, body.max_uses
    )
    db.commit()
    return CreationCodeCreated(**_code_out(row), code=code)


@router.post(
    "/admin/creation-codes/{code_id}/revoke", response_model=CreationCodeOut, dependencies=[NotDemo]
)
def revoke_creation_code(code_id: str, db: Db, admin: SuperAdmin) -> CreationCodeOut:
    row = db.get(CreationCode, _uuid(code_id))
    if row is None:
        raise NotFoundError("code not found")
    if row.revoked_at is None:
        db.execute(update(CreationCode).where(CreationCode.id == row.id).values(revoked_at=_now()))
        db.commit()
        db.refresh(row)
    return CreationCodeOut(**_code_out(row))


@router.get("/w/{ws}/join-tokens", response_model=list[JoinTokenOut])
def list_join_tokens(db: Db, ws: CurrentWorkspace, viewer: AdminViewer) -> list[JoinTokenOut]:
    rows = db.scalars(
        select(JoinToken)
        .where(JoinToken.workspace_id == ws.id)
        .order_by(JoinToken.created_at.desc())
    )
    return [JoinTokenOut(**_token_out(r)) for r in rows]


@router.post(
    "/w/{ws}/join-tokens", response_model=JoinTokenCreated, status_code=201, dependencies=[NotDemo]
)
def create_join_token(
    body: JoinTokenCreate,
    db: Db,
    ws: CurrentWorkspace,
    viewer: AdminViewer,
    settings: AppSettings,
) -> JoinTokenCreated:
    assert viewer.user_id is not None
    _check_caps(db, settings, ws.id, viewer.user_id, bool(body.email_to))
    row, token = access_codes.make_join_token(
        db, ws.id, viewer.user_id, body.role, body.label, body.expires_in_days, body.max_uses
    )
    link = f"{ui_origin(settings)}/signup?token={token}"
    queued = False  # True only means "accepted for sending", never "delivered"
    if body.email_to and mailer.is_configured(settings):
        queued = mailer.send_async(
            settings,
            body.email_to,
            f"You are invited to {ws.name} on DataForce",
            f"You were invited to join the workspace {ws.name} on DataForce.\n\n"
            f"Open this link to join (it works until {row.expires_at:%Y-%m-%d}):\n{link}\n",
        )
        if queued:
            row.emailed_at = _now()
    db.commit()
    return JoinTokenCreated(**_token_out(row), token=token, link=link, email_queued=queued)


@router.post(
    "/w/{ws}/join-tokens/{token_id}/revoke", response_model=JoinTokenOut, dependencies=[NotDemo]
)
def revoke_join_token(
    token_id: str, db: Db, ws: CurrentWorkspace, viewer: AdminViewer
) -> JoinTokenOut:
    row = db.get(JoinToken, _uuid(token_id))
    if row is None or row.workspace_id != ws.id:
        raise NotFoundError("token not found")
    if row.revoked_at is None:
        db.execute(update(JoinToken).where(JoinToken.id == row.id).values(revoked_at=_now()))
        db.commit()
        db.refresh(row)
    return JoinTokenOut(**_token_out(row))


def _check_caps(db, settings, ws_id: uuid.UUID, user_id: uuid.UUID, with_email: bool) -> None:
    now = _now()
    active = db.scalar(
        select(func.count())
        .select_from(JoinToken)
        .where(
            JoinToken.workspace_id == ws_id,
            JoinToken.revoked_at.is_(None),
            JoinToken.expires_at > now,
            JoinToken.uses < JoinToken.max_uses,
        )
    )
    if (active or 0) >= settings.join_tokens_max_active:
        raise HTTPException(
            status_code=409,
            detail="Too many active join links. Revoke some before creating more.",
        )
    if not (with_email and mailer.is_configured(settings)):
        return
    since = now - timedelta(hours=24)
    base = select(func.count()).select_from(JoinToken).where(JoinToken.emailed_at > since)
    if (db.scalar(base.where(JoinToken.workspace_id == ws_id)) or 0) >= (
        settings.invite_emails_per_workspace_per_day
    ):
        raise HTTPException(
            status_code=429, detail="Too many invitation emails today for this workspace."
        )
    if (db.scalar(base.where(JoinToken.created_by == user_id)) or 0) >= (
        settings.invite_emails_per_user_per_day
    ):
        raise HTTPException(status_code=429, detail="Too many invitation emails sent today.")


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise NotFoundError("not found") from None


def _now() -> datetime:
    return datetime.now(UTC)
