"""Meeting transcripts: import, list, read, delete (docs/M2B-CONTRACT.md section 5)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Query, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import defer

from app.api.deps import AppSettings, CurrentViewer, CurrentWorkspace, Db
from app.api.schemas import Page
from app.api.schemas_documents import (
    ChunkOut,
    ChunkTheme,
    DocumentDetail,
    DocumentOut,
    SpeakerOut,
)
from app.auth import visibility
from app.auth.viewer import Viewer
from app.db.models import Account, Document, DocumentChunk
from app.services import companies as company_svc
from app.services import documents as svc
from app.services import themes as theme_svc
from app.services._common import LIKE_ESCAPE, like_contains, require_account

router = APIRouter(tags=["documents"])


def _outs(
    db: Db, ws_id: uuid.UUID, docs: list[Document], viewer: Viewer | None = None
) -> list[DocumentOut]:
    ids = [d.id for d in docs]
    if not ids:
        return []
    names = dict(
        db.execute(
            select(Account.id, Account.name).where(Account.id.in_({d.account_id for d in docs}))
        ).all()
    )
    n_chunks = dict(
        db.execute(
            select(DocumentChunk.document_id, func.count())
            .where(DocumentChunk.document_id.in_(ids))
            .group_by(DocumentChunk.document_id)
        ).all()
    )
    speakers: dict[uuid.UUID, dict[str | None, SpeakerOut]] = defaultdict(dict)
    for doc_id, sp, cid, uid in db.execute(
        select(
            DocumentChunk.document_id,
            DocumentChunk.speaker,
            DocumentChunk.contact_id,
            DocumentChunk.user_id,
        )
        .where(DocumentChunk.document_id.in_(ids))
        .order_by(DocumentChunk.document_id, DocumentChunk.seq)
    ):
        speakers[doc_id].setdefault(sp, SpeakerOut(name=sp, contact_id=cid, user_id=uid))
    labels: dict[uuid.UUID, list[str]] = defaultdict(list)
    for doc_id, _chunk, _tid, label in theme_svc.chunk_theme_labels(db, ws_id, ids, viewer):
        if label not in labels[doc_id]:
            labels[doc_id].append(label)
    return [
        DocumentOut(
            id=d.id,
            account_id=d.account_id,
            account_name=names.get(d.account_id, ""),
            deal_id=d.deal_id,
            title=d.title,
            meeting_date=d.meeting_date,
            file_name=d.file_name,
            n_chars=d.n_chars,
            n_chunks=n_chunks.get(d.id, 0),
            language=d.language,
            speakers=list(speakers[d.id].values()),
            theme_labels=labels[d.id],
            created_at=d.created_at,
        )
        for d in docs
    ]


def _order(stmt):
    """Ordering for the list endpoints; the full transcript text is never fetched for them."""
    return stmt.options(defer(Document.text)).order_by(
        Document.meeting_date.desc().nulls_last(), Document.created_at.desc(), Document.id
    )


@router.post("/w/{ws}/accounts/{account_id}/documents", response_model=DocumentOut, status_code=201)
def upload_document(
    account_id: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    viewer: CurrentViewer,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=300)] = None,
    meeting_date: Annotated[date | None, Form()] = None,
    deal_id: Annotated[uuid.UUID | None, Form()] = None,
) -> DocumentOut:
    require_account(db, ws.id, account_id, viewer)
    data = file.file.read(settings.transcript_max_bytes + 1)
    doc = svc.import_file(
        db,
        ws.id,
        settings,
        account_id=account_id,
        file_name=file.filename,
        data=data,
        title=title,
        meeting_date=meeting_date,
        deal_id=deal_id,
        created_by_id=viewer.app_user_id,
        viewer=viewer,
    )
    db.commit()
    return _outs(db, ws.id, [doc], viewer)[0]


@router.get("/w/{ws}/accounts/{account_id}/documents", response_model=list[DocumentOut])
def account_documents(
    account_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> list[DocumentOut]:
    require_account(db, ws.id, account_id, viewer)
    stmt = _order(
        select(Document).where(
            Document.workspace_id == ws.id,
            Document.account_id == account_id,
            *visibility.conds(visibility.deal_gate(viewer, Document.deal_id)),
        )
    )
    return _outs(db, ws.id, list(db.scalars(stmt)), viewer)


@router.get("/w/{ws}/companies/{company_id}/documents", response_model=list[DocumentOut])
def company_documents(
    company_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> list[DocumentOut]:
    company_svc.require_company(db, ws.id, company_id, viewer)
    stmt = _order(
        select(Document)
        .join(Account, Account.id == Document.account_id)
        .where(
            Document.workspace_id == ws.id,
            Account.company_id == company_id,
            *visibility.conds(
                visibility.in_accounts(viewer, Document.account_id),
                visibility.deal_gate(viewer, Document.deal_id),
            ),
        )
    )
    return _outs(db, ws.id, list(db.scalars(stmt)), viewer)


@router.get("/w/{ws}/documents", response_model=Page[DocumentOut])
def list_documents(
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    q: Annotated[str | None, Query(max_length=200, pattern=r"^[^\x00-\x1f\x7f]*$")] = None,
    sort: Literal["meeting_date", "title", "created_at", "kind", "language"] | None = None,
    direction: Annotated[Literal["asc", "desc"], Query(alias="dir")] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> Page[DocumentOut]:
    cond = [
        Document.workspace_id == ws.id,
        *visibility.conds(
            visibility.in_accounts(viewer, Document.account_id),
            visibility.deal_gate(viewer, Document.deal_id),
        ),
    ]
    if q:
        cond.append(Document.title.ilike(like_contains(q), escape=LIKE_ESCAPE))
    total = db.scalar(select(func.count()).select_from(Document).where(*cond)) or 0
    stmt = select(Document).where(*cond).options(defer(Document.text))
    if sort:
        col = getattr(Document, sort)
        stmt = stmt.order_by((col.desc() if direction == "desc" else col.asc()).nulls_last())
        stmt = stmt.order_by(Document.id)
    else:
        stmt = _order(stmt)
    rows = list(db.scalars(stmt.limit(limit).offset(offset)))
    return Page(items=_outs(db, ws.id, rows, viewer), total=total, offset=offset, limit=limit)


@router.get("/w/{ws}/documents/{doc_id}", response_model=DocumentDetail)
def get_document(
    doc_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> DocumentDetail:
    doc = svc.require_document(db, ws.id, doc_id, viewer)
    base = _outs(db, ws.id, [doc], viewer)[0]
    chunks = list(
        db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.seq)
        )
    )
    return DocumentDetail(
        **base.model_dump(),
        text=doc.text,
        chunks=[
            ChunkOut(
                id=c.id,
                seq=c.seq,
                speaker=c.speaker,
                contact_id=c.contact_id,
                user_id=c.user_id,
                char_start=c.char_start,
                char_end=c.char_end,
            )
            for c in chunks
        ],
        chunk_themes=[
            ChunkTheme(chunk_id=cid, theme_id=tid, label=label)
            for _d, cid, tid, label in theme_svc.chunk_theme_labels(db, ws.id, [doc.id], viewer)
        ],
    )


@router.delete("/w/{ws}/documents/{doc_id}", status_code=204)
def delete_document(
    doc_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> Response:
    svc.delete_document(db, ws.id, doc_id, viewer)
    db.commit()
    return Response(status_code=204)
