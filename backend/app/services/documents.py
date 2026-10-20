"""Meeting transcripts: import, parsing into chunks, listing (M2b section 5)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import visibility
from app.auth.viewer import Viewer
from app.config import Settings
from app.db.models import AppUser, Contact, Document, DocumentChunk, OrgProposal
from app.domain.enums import ProposalStatus
from app.services import org_ai
from app.services._common import like_contains, require, require_account, require_deal
from app.services.errors import InvalidInputError, NotFoundError
from app.services.textclean import scrub_text
from app.transcripts import importer
from app.transcripts.names import Candidate, match_speaker
from app.transcripts.parse import chunk_text, detect_language

MAX_CHUNKS_PER_DOCUMENT = 5_000


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
    viewer: Viewer | None = None,
) -> Document:
    """Clean, parse and chunk `text`, then store the document and its chunks."""
    require_account(session, ws_id, account_id, viewer)
    if deal_id is not None:
        deal = require_deal(session, ws_id, deal_id, viewer)
        if deal.account_id != account_id:
            raise InvalidInputError("the deal does not belong to this account")
    if created_by_id is not None:
        require(session, AppUser, ws_id, created_by_id)
    clean = importer.clean_text(scrub_text(text))
    if not clean:
        raise InvalidInputError("the transcript is empty")
    parsed = chunk_text(clean)
    if len(parsed) > MAX_CHUNKS_PER_DOCUMENT:
        raise InvalidInputError(
            f"the transcript has {len(parsed)} speaker turns; "
            f"the limit is {MAX_CHUNKS_PER_DOCUMENT} "
            "(split the file or remove the speaker labels of the short lines)"
        )
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
    for ch in parsed:
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
    created_by_id: uuid.UUID | None = None,
    viewer: Viewer | None = None,
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
        created_by_id=created_by_id,
        viewer=viewer,
    )


def require_document(
    session: Session, ws_id: uuid.UUID, doc_id: uuid.UUID, viewer: Viewer | None = None
) -> Document:
    doc = session.get(Document, doc_id)
    if doc is None or doc.workspace_id != ws_id:
        raise NotFoundError("document not found")
    if not visibility.can_see_account(session, viewer, doc.account_id):
        raise NotFoundError("document not found")
    if doc.deal_id is not None and not visibility.can_see_deal(session, viewer, doc.deal_id):
        raise NotFoundError("document not found")
    return doc


def delete_document(
    session: Session, ws_id: uuid.UUID, doc_id: uuid.UUID, viewer: Viewer | None = None
) -> None:
    doc = require_document(session, ws_id, doc_id, viewer)
    if viewer is not None:
        visibility.require_delete(viewer, doc.created_by_id)
    _forget_quotes(session, ws_id, doc_id)
    session.delete(doc)
    session.flush()


_QUOTE_KEYS = (
    "excerpt",
    "speaker",
    "chunk_id",
    "char_start",
    "char_end",
    "manager_excerpt",
    "manager_char_start",
    "manager_char_end",
)


def _forget_quotes(session: Session, ws_id: uuid.UUID, doc_id: uuid.UUID) -> None:
    """Org proposals quoting a deleted transcript: open ones go, since their only evidence is
    gone; decided ones keep the decision but lose the quote and the speaker."""
    for prop in session.scalars(
        select(OrgProposal).where(
            OrgProposal.workspace_id == ws_id,
            OrgProposal.evidence["document_id"].astext == str(doc_id),
        )
    ):
        if prop.status in (ProposalStatus.PROPOSED.value, ProposalStatus.AMBIGUOUS.value):
            session.delete(prop)
        else:
            ev = {k: v for k, v in prop.evidence.items() if k not in _QUOTE_KEYS}
            prop.evidence = {**ev, "document_deleted": True}


def count_documents(session: Session, ws_id: uuid.UUID, viewer: Viewer | None = None) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(Document)
            .where(
                Document.workspace_id == ws_id,
                *visibility.conds(
                    visibility.in_accounts(viewer, Document.account_id),
                    visibility.deal_gate(viewer, Document.deal_id),
                ),
            )
        )
        or 0
    )


# --- GDPR: redact an erased contact from the transcripts (SR12-03) ------------------------
ERASED = "[erased]"
NAME_MASK = "[name]"


def _placeholder(label: str, n: int) -> str:
    """`label` padded with spaces to exactly n characters (stars when n is shorter than label)."""
    return label.ljust(n) if n >= len(label) else "*" * n


def name_pattern(full_name: str) -> re.Pattern[str] | None:
    """Case-insensitive pattern for the full name and for first + last name (either order)."""
    tokens = unicodedata.normalize("NFC", full_name).split()
    if not tokens:
        return None
    esc = [re.escape(t) for t in tokens]
    alts = {r"\s+".join(esc)}
    if len(tokens) >= 3:
        alts.add(rf"{esc[0]}\s+{esc[-1]}")
    if len(tokens) >= 2:
        alts.add(rf"{esc[-1]}\s+{esc[0]}")
    body = "|".join(sorted(alts, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{body})(?!\w)", re.IGNORECASE)


def _mask_name(rx: re.Pattern[str], text: str) -> str:
    """`text` with every name occurrence replaced by a same-length placeholder."""
    return rx.sub(lambda m: _placeholder(NAME_MASK, len(m.group(0))), text)


def _redact_text(
    text: str,
    rx: re.Pattern[str] | None,
    erased: list[tuple[int, int]],
    labels: list[tuple[int, int]],
) -> str:
    buf = list(text)
    if rx is not None:
        for m in rx.finditer(text):
            buf[m.start() : m.end()] = _placeholder(NAME_MASK, m.end() - m.start())
    for a, b in labels:
        buf[a:b] = _placeholder(NAME_MASK, b - a)
    for a, b in erased:
        buf[a:b] = _placeholder(ERASED, b - a)
    return "".join(buf)


def redact_contact(session: Session, ws_id: uuid.UUID, contact: Contact) -> None:
    """Remove a contact (about to be erased) from the account's transcripts, in the caller's
    transaction and WITHOUT moving any offset: their turns become "[erased]" padded to the same
    length, their name (full, or first + last) becomes "[name]" padded likewise, in `document.text`
    and in every chunk, and the excerpts of the remaining org proposals follow. Notes written by
    other people that mention them are out of scope (see the SR12 resolution)."""
    org_ai.purge_account_cache(session, ws_id, contact.account_id)
    rx = name_pattern(contact.full_name)
    own = list(
        session.scalars(
            select(DocumentChunk).where(
                DocumentChunk.workspace_id == ws_id, DocumentChunk.contact_id == contact.id
            )
        )
    )
    own_docs = {c.document_id for c in own}
    last = contact.full_name.split()[-1] if contact.full_name.split() else ""
    cond = [Document.id.in_(own_docs)] if own_docs else []
    if last:
        cond.append(Document.text.ilike(like_contains(last), escape="\\"))
    if not cond:
        return
    docs = list(
        session.scalars(
            select(Document).where(
                Document.workspace_id == ws_id,
                Document.account_id == contact.account_id,
                or_(*cond),
            )
        )
    )
    old_texts: dict[uuid.UUID, str] = {}
    new_texts: dict[uuid.UUID, str] = {}
    for doc in docs:
        mine = [c for c in own if c.document_id == doc.id]
        erased = [(c.char_start, c.char_end) for c in mine]
        labels: list[tuple[int, int]] = []
        for c in mine:
            if not c.speaker:
                continue
            line = doc.text.rfind("\n", 0, c.char_start) + 1
            at = doc.text.find(c.speaker, line, c.char_start)
            if at >= 0:
                labels.append((at, at + len(c.speaker)))
        new = _redact_text(doc.text, rx, erased, labels)
        if rx is not None:
            doc.title = _mask_name(rx, doc.title)
            if doc.file_name:
                doc.file_name = _mask_name(rx, doc.file_name)
        if new == doc.text:
            continue
        old_texts[doc.id], new_texts[doc.id] = doc.text, new
        doc.text = new
        doc.sha256 = hashlib.sha256(new.encode("utf-8")).hexdigest()
    if new_texts:
        for ch in session.scalars(
            select(DocumentChunk).where(
                DocumentChunk.workspace_id == ws_id,
                DocumentChunk.document_id.in_(list(new_texts)),
            )
        ):
            ch.text = new_texts[ch.document_id][ch.char_start : ch.char_end]
            if ch.contact_id == contact.id:
                ch.speaker = ERASED if ch.speaker else None
            elif ch.speaker and rx is not None:
                ch.speaker = _mask_name(rx, ch.speaker)
    own_labels = {c.speaker for c in own if c.speaker}
    for prop in session.scalars(
        select(OrgProposal).where(
            OrgProposal.workspace_id == ws_id,
            OrgProposal.account_id == contact.account_id,
            OrgProposal.contact_id != contact.id,
        )
    ):
        ev = dict(prop.evidence or {})
        excerpt = ev.get("excerpt")
        if not isinstance(excerpt, str):
            continue
        doc_id = _uuid_or_none(ev.get("document_id"))
        a, b = ev.get("char_start"), ev.get("char_end")
        if (
            doc_id in new_texts
            and isinstance(a, int)
            and isinstance(b, int)
            and old_texts[doc_id][a:b] == excerpt
        ):
            ev["excerpt"] = new_texts[doc_id][a:b]
        elif rx is not None:
            ev["excerpt"] = _mask_name(rx, excerpt)
        mex = ev.get("manager_excerpt")
        ma, mb = ev.get("manager_char_start"), ev.get("manager_char_end")
        if isinstance(mex, str):
            if (
                doc_id in new_texts
                and isinstance(ma, int)
                and isinstance(mb, int)
                and old_texts[doc_id][ma:mb] == mex
            ):
                ev["manager_excerpt"] = new_texts[doc_id][ma:mb]
            elif rx is not None:
                ev["manager_excerpt"] = _mask_name(rx, mex)
        if ev.get("speaker") in own_labels:
            ev["speaker"] = ERASED
        elif isinstance(ev.get("speaker"), str) and rx is not None:
            ev["speaker"] = _mask_name(rx, ev["speaker"])
        if ev != prop.evidence:
            prop.evidence = ev
    session.flush()


def _uuid_or_none(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
