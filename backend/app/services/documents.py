"""Meeting transcripts: import, parsing into chunks, listing (M2b section 5)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import AppUser, Contact, Document, DocumentChunk
from app.services._common import require, require_account, require_deal
from app.services.errors import InvalidInputError, NotFoundError
from app.services.textclean import scrub_text
from app.transcripts import importer
from app.transcripts.names import Candidate, match_speaker
from app.transcripts.parse import chunk_text, detect_language


def add_document(
    session: Session,
    ws_id: uuid.UUID,
    *,
    account_id: uuid.UUID,
    title: str,
    text: str,
    meeting_date: date | None = None,
    deal_id: uuid.UUID | None = None,
    file_name: str | None = None,
    media_type: str | None = None,
    size_bytes: int | None = None,
    source: str = "manual",
    created_by_id: uuid.UUID | None = None,
) -> Document:
    """Clean, parse and chunk `text`, then store the document and its chunks."""
    require_account(session, ws_id, account_id)
    if deal_id is not None:
        deal = require_deal(session, ws_id, deal_id)
        if deal.account_id != account_id:
            raise InvalidInputError("the deal does not belong to this account")
    if created_by_id is not None:
        require(session, AppUser, ws_id, created_by_id)
    clean = importer.clean_text(scrub_text(text))
    if not clean:
        raise InvalidInputError("the transcript is empty")
    title = scrub_text(title).strip()[:300] or "Meeting"
    doc = Document(
        workspace_id=ws_id,
        account_id=account_id,
        deal_id=deal_id,
        kind="transcript",
        title=title,
        meeting_date=meeting_date,
        file_name=file_name,
        media_type=media_type,
        sha256=hashlib.sha256(clean.encode("utf-8")).hexdigest(),
        size_bytes=size_bytes if size_bytes is not None else len(clean.encode("utf-8")),
        text=clean,
        n_chars=len(clean),
        language=detect_language(clean),
        source=source,
        created_by_id=created_by_id,
    )
    session.add(doc)
    session.flush()
    contacts = [
        Candidate(c.id, c.full_name)
        for c in session.scalars(
            select(Contact).where(Contact.workspace_id == ws_id, Contact.account_id == account_id)
        )
    ]
    users = [
        Candidate(u.id, u.display_name)
        for u in session.scalars(select(AppUser).where(AppUser.workspace_id == ws_id))
    ]
    cache: dict[str | None, tuple[uuid.UUID | None, uuid.UUID | None]] = {}
    for ch in chunk_text(clean):
        if ch.speaker not in cache:
            m = match_speaker(ch.speaker, contacts, users)
            cache[ch.speaker] = (
                m.id if m and m.kind == "contact" else None,
                m.id if m and m.kind == "user" else None,
            )
        contact_id, user_id = cache[ch.speaker]
        session.add(
            DocumentChunk(
                workspace_id=ws_id,
                document_id=doc.id,
                seq=ch.seq,
                speaker=ch.speaker,
                contact_id=contact_id,
                user_id=user_id,
                char_start=ch.start,
                char_end=ch.end,
                text=ch.text,
            )
        )
    session.flush()
    return doc


def import_file(
    session: Session,
    ws_id: uuid.UUID,
    settings: Settings,
    *,
    account_id: uuid.UUID,
    file_name: str | None,
    data: bytes,
    title: str | None,
    meeting_date: date | None,
    deal_id: uuid.UUID | None,
) -> Document:
    name = importer.sanitize_name(file_name)
    try:
        ex = importer.extract(
            name,
            data,
            max_bytes=settings.transcript_max_bytes,
            max_pages=settings.transcript_max_pages,
            max_chars=settings.transcript_max_chars,
        )
    except importer.ImportRefused as exc:
        raise InvalidInputError(str(exc)) from None
    return add_document(
        session,
        ws_id,
        account_id=account_id,
        title=(title or "").strip() or name.rsplit(".", 1)[0],
        text=ex.text,
        meeting_date=meeting_date,
        deal_id=deal_id,
        file_name=name,
        media_type=ex.media_type,
        size_bytes=len(data),
        source="upload",
    )


def require_document(session: Session, ws_id: uuid.UUID, doc_id: uuid.UUID) -> Document:
    doc = session.get(Document, doc_id)
    if doc is None or doc.workspace_id != ws_id:
        raise NotFoundError("document not found")
    return doc


def delete_document(session: Session, ws_id: uuid.UUID, doc_id: uuid.UUID) -> None:
    session.delete(require_document(session, ws_id, doc_id))
    session.flush()


def count_documents(session: Session, ws_id: uuid.UUID) -> int:
    return (
        session.scalar(
            select(func.count()).select_from(Document).where(Document.workspace_id == ws_id)
        )
        or 0
    )
