"""Stage control and the timeline of a deal or an account (M4)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentViewer, CurrentWorkspace, Db
from app.api.routes.crm import _deals_out
from app.api.schemas import DealOut
from app.api.schemas_activity import MoveStage, StageEventOut, TimelineItem, TimelinePage
from app.services import stage_events, timeline, users

router = APIRouter(tags=["pipeline"])


@router.post("/w/{ws}/deals/{deal_id}/move", response_model=DealOut)
def move_stage(
    deal_id: uuid.UUID, body: MoveStage, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> DealOut:
    deal = stage_events.move_stage(
        db,
        ws.id,
        deal_id,
        body.stage,
        on=body.changed_on,
        lost_reason=body.lost_reason,
        changed_by_id=viewer.app_user_id,
        viewer=viewer,
    )
    db.commit()
    return _deals_out(db, ws.id, [deal])[0]


@router.get("/w/{ws}/deals/{deal_id}/stage-events", response_model=list[StageEventOut])
def list_stage_events(
    deal_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> list[StageEventOut]:
    rows = stage_events.list_events(db, ws.id, deal_id, viewer)
    names = users.user_names(db, ws.id, [r.changed_by_id for r in rows if r.changed_by_id])
    return [
        StageEventOut(
            id=r.id,
            deal_id=r.deal_id,
            from_stage=r.from_stage,
            to_stage=r.to_stage,
            changed_at=r.changed_at,
            changed_by_id=r.changed_by_id,
            changed_by_name=names.get(r.changed_by_id) if r.changed_by_id else None,
            source=r.source,
        )
        for r in rows
    ]


def _page(items: list[timeline.Item], nxt: str | None) -> TimelinePage:
    return TimelinePage(
        items=[
            TimelineItem(
                id=i.id,
                kind=i.kind,
                at=i.at,
                title=i.title,
                title_untrusted=i.title_untrusted,
                summary=i.summary,
                summary_untrusted=i.summary_untrusted,
                author_name=i.author_name,
                refs=i.refs,
            )
            for i in items
        ],
        next_before=nxt,
    )


def _kinds(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    return {k for k in (p.strip() for p in raw.split(",")) if k}


Limit = Annotated[int, Query(ge=1, le=200)]


@router.get("/w/{ws}/deals/{deal_id}/timeline", response_model=TimelinePage)
def deal_timeline(
    deal_id: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    limit: Limit = 50,
    before: Annotated[str | None, Query(max_length=200)] = None,
    kinds: Annotated[str | None, Query(max_length=200)] = None,
) -> TimelinePage:
    items, nxt = timeline.build_timeline(
        db, ws.id, deal_id=deal_id, kinds=_kinds(kinds), limit=limit, before=before, viewer=viewer
    )
    return _page(items, nxt)


@router.get("/w/{ws}/accounts/{account_id}/timeline", response_model=TimelinePage)
def account_timeline(
    account_id: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    limit: Limit = 50,
    before: Annotated[str | None, Query(max_length=200)] = None,
    kinds: Annotated[str | None, Query(max_length=200)] = None,
) -> TimelinePage:
    items, nxt = timeline.build_timeline(
        db,
        ws.id,
        account_id=account_id,
        kinds=_kinds(kinds),
        limit=limit,
        before=before,
        viewer=viewer,
    )
    return _page(items, nxt)
