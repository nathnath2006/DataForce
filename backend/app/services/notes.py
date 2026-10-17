"""Notes on contacts. Append-only (DB trigger): corrections are new rows, deletes are soft."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import Note
from app.services import _appendonly as ao
from app.services._common import require_contact

_PARENT = "contact_id"


def add_note(
    session: Session,
    ws_id: uuid.UUID,
    contact_id: uuid.UUID,
    author_id: uuid.UUID | None,
    body: str,
    *,
    created_at: datetime | None = None,
) -> Note:
    require_contact(session, ws_id, contact_id)
    return ao.add(session, Note, _PARENT, ws_id, contact_id, author_id, body, created_at=created_at)


def correct_note(
    session: Session,
    ws_id: uuid.UUID,
    note_id: uuid.UUID,
    author_id: uuid.UUID | None,
    new_body: str,
    *,
    created_at: datetime | None = None,
) -> Note:
    return ao.correct(
        session, Note, _PARENT, ws_id, note_id, author_id, new_body, created_at=created_at
    )


def delete_note(
    session: Session, ws_id: uuid.UUID, note_id: uuid.UUID, by_id: uuid.UUID | None
) -> Note:
    return ao.soft_delete(session, Note, _PARENT, ws_id, note_id, by_id)


def current_notes(session: Session, ws_id: uuid.UUID, contact_id: uuid.UUID) -> list[Note]:
    return ao.current(session, Note, _PARENT, ws_id, contact_id)


def note_history(session: Session, ws_id: uuid.UUID, note_id: uuid.UUID) -> list[Note]:
    return ao.history(session, Note, _PARENT, ws_id, note_id)
