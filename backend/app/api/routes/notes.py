"""Notes (on contacts) and comments (on accounts): append-only, same five routes each."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import APIRouter

from app.api.deps import CurrentViewer, CurrentWorkspace, Db
from app.api.schemas import NoteCorrect, NoteCreate, NoteOut
from app.db.models import Comment, Note
from app.domain.schemas import NoteRead
from app.services import comments, notes, users
from app.services._common import require_contact

router = APIRouter(tags=["notes"])


def _out(db: Db, ws_id: uuid.UUID, rows: Sequence[Note | Comment]) -> list[NoteOut]:
    ids = {x for r in rows for x in (r.author_id, r.deleted_by_id) if x is not None}
    names = users.user_names(db, ws_id, list(ids))
    return [
        NoteOut(
            **NoteRead.model_validate(r).model_dump(),
            author_name=names.get(r.author_id) if r.author_id else None,
            deleted_by_name=names.get(r.deleted_by_id) if r.deleted_by_id else None,
        )
        for r in rows
    ]


# --- notes ----------------------------------------------------------------------------------
@router.get("/w/{ws}/contacts/{contact_id}/notes", response_model=list[NoteOut])
def list_notes(
    contact_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> list[NoteOut]:
    require_contact(db, ws.id, contact_id, viewer)
    rows = notes.current_notes(db, ws.id, contact_id, viewer)
    return _out(db, ws.id, sorted(rows, key=lambda r: r.created_at, reverse=True))


@router.post("/w/{ws}/contacts/{contact_id}/notes", response_model=NoteOut, status_code=201)
def add_note(
    contact_id: uuid.UUID, body: NoteCreate, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> NoteOut:
    row = notes.add_note(db, ws.id, contact_id, viewer.app_user_id, body.body, viewer=viewer)
    db.commit()
    return _out(db, ws.id, [row])[0]


@router.post("/w/{ws}/notes/{note_id}/correct", response_model=NoteOut, status_code=201)
def correct_note(
    note_id: uuid.UUID, body: NoteCorrect, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> NoteOut:
    row = notes.correct_note(db, ws.id, note_id, viewer.app_user_id, body.body, viewer=viewer)
    db.commit()
    return _out(db, ws.id, [row])[0]


@router.delete("/w/{ws}/notes/{note_id}", response_model=NoteOut)
def delete_note(note_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer) -> NoteOut:
    row = notes.delete_note(db, ws.id, note_id, viewer.app_user_id, viewer)
    db.commit()
    return _out(db, ws.id, [row])[0]


@router.get("/w/{ws}/notes/{note_id}/history", response_model=list[NoteOut])
def note_history(
    note_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> list[NoteOut]:
    return _out(db, ws.id, notes.note_history(db, ws.id, note_id, viewer))


# --- comments -------------------------------------------------------------------------------
@router.get("/w/{ws}/accounts/{account_id}/comments", response_model=list[NoteOut])
def list_comments(
    account_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> list[NoteOut]:
    rows = comments.current_comments(db, ws.id, account_id, viewer)
    return _out(db, ws.id, sorted(rows, key=lambda r: r.created_at, reverse=True))


@router.post("/w/{ws}/accounts/{account_id}/comments", response_model=NoteOut, status_code=201)
def add_comment(
    account_id: uuid.UUID, body: NoteCreate, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> NoteOut:
    row = comments.add_comment(db, ws.id, account_id, viewer.app_user_id, body.body, viewer=viewer)
    db.commit()
    return _out(db, ws.id, [row])[0]


@router.post("/w/{ws}/comments/{comment_id}/correct", response_model=NoteOut, status_code=201)
def correct_comment(
    comment_id: uuid.UUID, body: NoteCorrect, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> NoteOut:
    row = comments.correct_comment(
        db, ws.id, comment_id, viewer.app_user_id, body.body, viewer=viewer
    )
    db.commit()
    return _out(db, ws.id, [row])[0]


@router.delete("/w/{ws}/comments/{comment_id}", response_model=NoteOut)
def delete_comment(
    comment_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> NoteOut:
    row = comments.delete_comment(db, ws.id, comment_id, viewer.app_user_id, viewer)
    db.commit()
    return _out(db, ws.id, [row])[0]


@router.get("/w/{ws}/comments/{comment_id}/history", response_model=list[NoteOut])
def comment_history(
    comment_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> list[NoteOut]:
    return _out(db, ws.id, comments.comment_history(db, ws.id, comment_id, viewer))
