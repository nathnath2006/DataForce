"""Theme analysis: discovery by code, naming by the AI or by keywords, storage (M2b section 5)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.db.models import Account, Document, DocumentChunk, Run, Theme, ThemeAssignment
from app.domain.enums import RunKind, RunStatus
from app.services.errors import InvalidInputError
from app.services.runs import finish_run, start_run
from app.services.textclean import scrub_text
from app.themes import discover as disc
from app.themes.naming import Named, keyword_name


@dataclass(frozen=True)
class NamingInput:
    top_terms: list[str]
    excerpts: list[str]


# Names a batch of themes; None for one means "use the keywords". The route builds it from the
# workspace AI model; tests give a fake. It must not raise for one failing theme.
Namer = Callable[[list[NamingInput]], list[Named | None]]


@dataclass(frozen=True)
class ThemeRunResult:
    run: Run
    k: int
    n_chunks_used: int
    n_unassigned: int
    dropped: list[disc.Dropped]


def latest_run(db: Session, ws_id: uuid.UUID) -> Run | None:
    return db.scalar(
        select(Run)
        .where(
            Run.workspace_id == ws_id,
            Run.kind == RunKind.THEME_ANALYSIS.value,
            Run.status == RunStatus.SUCCEEDED.value,
        )
        .order_by(Run.started_at.desc(), Run.id)
        .limit(1)
    )


def _input_chunks(db: Session, ws_id: uuid.UUID, customer_only: bool):
    stmt = (
        select(DocumentChunk, Document.account_id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.workspace_id == ws_id)
        .order_by(Document.created_at, Document.id, DocumentChunk.seq)
        .limit(disc.MAX_CHUNKS)
    )
    if customer_only:
        stmt = stmt.where(DocumentChunk.contact_id.is_not(None))
    return list(db.execute(stmt).all())


def run_themes(
    db: Session,
    ws_id: uuid.UUID,
    *,
    k: int,
    speakers: str = "customer",
    namer: Namer | None = None,
) -> ThemeRunResult:
    """Find themes in the workspace's chunks and store them as the latest run."""
    if not 2 <= k <= 30:
        raise InvalidInputError("k must be between 2 and 30")
    if speakers not in ("customer", "all"):
        raise InvalidInputError("speakers must be customer or all")
    rows = _input_chunks(db, ws_id, speakers == "customer")
    if not rows and speakers == "customer":
        rows = _input_chunks(db, ws_id, False)  # no matched customer speaker: use everyone
    run = start_run(
        db, RunKind.THEME_ANALYSIS, ws_id, params={"k": k, "speakers": speakers, "ai": bool(namer)}
    )
    try:
        found = disc.discover([c.text for c, _ in rows], k)
        inputs = [
            NamingInput(
                t.top_terms,
                [
                    disc.best_sentence(rows[i][0].text, t.top_terms)
                    for i, _ in sorted(t.members, key=lambda m: (-m[1], m[0]))[: disc.N_EXCERPTS]
                ],
            )
            for t in found.themes
        ]
        names: list[Named | None] = namer(inputs) if namer and inputs else [None] * len(inputs)
        for t, named in zip(found.themes, names, strict=True):
            named = named or keyword_name(t.top_terms)
            theme = Theme(
                workspace_id=ws_id,
                run_id=run.id,
                seq=t.seq,
                label=scrub_text(named.label),
                description=scrub_text(named.description) if named.description else None,
                kind=named.kind,
                named_by=named.named_by,
                top_terms=t.top_terms,
                n_chunks=len(t.members),
                n_documents=len({rows[i][0].document_id for i, _ in t.members}),
                n_accounts=len({rows[i][1] for i, _ in t.members}),
            )
            db.add(theme)
            db.flush()
            db.add_all(
                ThemeAssignment(
                    theme_id=theme.id,
                    chunk_id=rows[i][0].id,
                    workspace_id=ws_id,
                    weight=w,
                )
                for i, w in t.members
            )
        db.flush()
    except disc.ThemeError as exc:
        finish_run(db, run, RunStatus.FAILED, error=str(exc))
        db.commit()
        raise InvalidInputError(str(exc)) from None
    except Exception:
        finish_run(db, run, RunStatus.FAILED, error="theme analysis failed")
        db.commit()
        raise
    finish_run(
        db,
        run,
        RunStatus.SUCCEEDED,
        result={
            "n_chunks_used": found.n_used,
            "n_unassigned": found.n_unassigned,
            "n_themes": len(found.themes),
            "dropped": [{"top_terms": d.top_terms, "n_chunks": d.n_chunks} for d in found.dropped],
        },
    )
    return ThemeRunResult(run, k, found.n_used, found.n_unassigned, found.dropped)


# --- reading -------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ExcerptRow:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    account_id: uuid.UUID
    account_name: str
    meeting_date: date | None
    speaker: str | None
    text: str


@dataclass(frozen=True)
class ThemeView:
    theme: Theme
    n_chunks: int
    n_documents: int
    n_accounts: int
    excerpts: list[ExcerptRow]


def themes_of_run(db: Session, ws_id: uuid.UUID, run_id: uuid.UUID) -> list[ThemeView]:
    """The themes of a run with counts recomputed from the current assignments (a deleted
    document no longer counts) and the 3 highest-weight excerpts."""
    themes = list(
        db.scalars(
            select(Theme)
            .where(Theme.workspace_id == ws_id, Theme.run_id == run_id)
            .order_by(Theme.seq)
        )
    )
    counts = {
        r[0]: r[1:]
        for r in db.execute(
            select(
                ThemeAssignment.theme_id,
                func.count(),
                func.count(distinct(DocumentChunk.document_id)),
                func.count(distinct(Document.account_id)),
            )
            .join(DocumentChunk, DocumentChunk.id == ThemeAssignment.chunk_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(ThemeAssignment.workspace_id == ws_id)
            .where(ThemeAssignment.theme_id.in_([t.id for t in themes]))
            .group_by(ThemeAssignment.theme_id)
        )
    }
    views = []
    for t in themes:
        top = db.execute(
            select(DocumentChunk, Document, Account.name)
            .select_from(ThemeAssignment)
            .join(DocumentChunk, DocumentChunk.id == ThemeAssignment.chunk_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(Account, Account.id == Document.account_id)
            .where(ThemeAssignment.theme_id == t.id)
            .order_by(ThemeAssignment.weight.desc(), DocumentChunk.id)
            .limit(disc.N_EXCERPTS)
        ).all()
        n, nd, na = counts.get(t.id, (0, 0, 0))
        views.append(
            ThemeView(
                t,
                n,
                nd,
                na,
                [
                    ExcerptRow(
                        c.id,
                        d.id,
                        d.account_id,
                        name,
                        d.meeting_date,
                        c.speaker,
                        disc.best_sentence(c.text, t.top_terms),
                    )
                    for c, d, name in top
                ],
            )
        )
    return views


def chunk_theme_labels(
    db: Session, ws_id: uuid.UUID, document_ids: Sequence[uuid.UUID]
) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, str]]:
    """(document_id, chunk_id, theme_id, label) from the latest run, for these documents."""
    run = latest_run(db, ws_id)
    if run is None or not document_ids:
        return []
    return [
        tuple(r)  # type: ignore[misc]
        for r in db.execute(
            select(DocumentChunk.document_id, DocumentChunk.id, Theme.id, Theme.label)
            .select_from(ThemeAssignment)
            .join(Theme, Theme.id == ThemeAssignment.theme_id)
            .join(DocumentChunk, DocumentChunk.id == ThemeAssignment.chunk_id)
            .where(
                Theme.run_id == run.id,
                ThemeAssignment.workspace_id == ws_id,
                DocumentChunk.document_id.in_(document_ids),
            )
            .order_by(Theme.seq, DocumentChunk.seq)
        )
    ]
