"""Users: the sales reps (deal owners, note authors)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppUser
from app.domain.schemas import UserIn
from app.services._common import require_workspace
from app.services.errors import AlreadyExistsError
from app.services.textclean import scrub_optional, scrub_text


def create_user(session: Session, ws_id: uuid.UUID, data: UserIn) -> AppUser:
    require_workspace(session, ws_id)
    email = scrub_optional(data.email)
    if email is not None:
        taken = session.scalars(
            select(AppUser.id).where(AppUser.workspace_id == ws_id, AppUser.email == email)
        ).first()
        if taken is not None:
            raise AlreadyExistsError("a user with this email already exists in the workspace")
    user = AppUser(
        workspace_id=ws_id,
        display_name=scrub_text(data.display_name),
        email=email,
        role=data.role.value,
    )
    session.add(user)
    session.flush()
    return user


def list_users(session: Session, ws_id: uuid.UUID) -> list[AppUser]:
    stmt = (
        select(AppUser)
        .where(AppUser.workspace_id == ws_id)
        .order_by(AppUser.display_name, AppUser.id)
    )
    return list(session.scalars(stmt))
