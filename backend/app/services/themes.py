"""Theme analysis: discovery by code, naming by the AI or by keywords, storage (M2b section 5)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    AppUser,
    Contact,
    Document,
    DocumentChunk,
    Run,
    Theme,
    ThemeAssignment,
)
from app.domain.enums import RunKind, RunStatus
from app.services.errors import InvalidInputError
from app.services.runs import finish_run, start_run
from app.services.textclean import scrub_text
from app.themes import discover as disc
from app.themes import lexicon
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
    known_themes: list[str]


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


def _person_names(db: Session, ws_id: uuid.UUID) -> list[str]:
    return [
        *db.scalars(select(Contact.full_name).where(Contact.workspace_id == ws_id)),
        *db.scalars(select(AppUser.display_name).where(AppUser.workspace_id == ws_id)),
    ]


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
        names = _person_names(db, ws_id)
        texts = [c.text for c, _ in rows]
        doc_ids = [c.document_id for c, _ in rows]
        if len(texts) < disc.MIN_INPUT_CHUNKS:
            raise disc.ThemeError("not enough transcript text to find themes")
        known = lexicon.match_known(texts, names, doc_ids, max_chunks=disc.MAX_CHUNKS)
        try:
            found = disc.discover(texts, max(2, k // 2), names, doc_ids, skip=known.matched)
        except disc.ThemeError:
            if not known.found:
                raise
            found = disc.Discovery([], [], min(len(texts), disc.MAX_CHUNKS), 0)
        # Excerpts are exact quotes, but person names never reach the AI namer. Only discovered
        # topics are named by the AI; known themes keep their catalog label.
        inputs = [
            NamingInput(t.top_terms, [disc.mask_names(sent, names) for _, sent in t.excerpts])
            for t in found.themes
        ]
        named_all: list[Named | None] = namer(inputs) if namer and inputs else [None] * len(inputs)
        planned = [
            (
                f.label,
                f.description,
                f.kind,
                "lexicon",
                f.top_terms,
                f.members,
            )
            for f in known.found
        ]
        for t, named in zip(found.themes, named_all, strict=True):
            named = named or keyword_name(t.top_terms)
            planned.append(
                (named.label, named.description, named.kind, named.named_by, t.top_terms, t.members)
            )
        assigned: set[int] = set()
        for seq, (label, desc, kind, by, terms, members) in enumerate(planned, 1):
            assigned.update(i for i, _ in members)
            theme = Theme(
                workspace_id=ws_id,
                run_id=run.id,
                seq=seq,
                label=scrub_text(label),
                description=scrub_text(desc) if desc else None,
                kind=kind,
                named_by=by,
                top_terms=terms,
                n_chunks=len(members),
                n_documents=len({rows[i][0].document_id for i, _ in members}),
                n_accounts=len({rows[i][1] for i, _ in members}),
            )
            db.add(theme)
            db.flush()
            db.add_all(
                ThemeAssignment(
                    theme_id=theme.id, chunk_id=rows[i][0].id, workspace_id=ws_id, weight=w
                )
                for i, w in members
            )
        db.flush()
        known_ids = [f.id for f in known.found]
        n_unassigned = found.n_used - len({i for i in assigned if i < found.n_used})
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
            "n_unassigned": n_unassigned,
            "n_themes": len(planned),
            "known_themes": known_ids,
            "dropped": [{"top_terms": d.top_terms, "n_chunks": d.n_chunks} for d in found.dropped],
        },
    )
    return ThemeRunResult(run, k, found.n_used, n_unassigned, found.dropped, known_ids)


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


def _distinct_documents(rows: list) -> list:
    """Rows from distinct documents first, then the rest (order kept)."""
    seen: set[uuid.UUID] = set()
    first, rest = [], []
    for r in rows:
        (rest if r[1].id in seen else first).append(r)
        seen.add(r[1].id)
    return first + rest


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
            .limit(disc.N_EXCERPTS * 10)
        ).all()
        top = _distinct_documents(top)[: disc.N_EXCERPTS]
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
                        lexicon.best_known_sentence(t.label, c.text)
                        if t.named_by == "lexicon"
                        else disc.best_sentence(c.text, t.top_terms),
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
