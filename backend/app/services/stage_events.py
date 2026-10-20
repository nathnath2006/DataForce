"""Stage control: move a deal to a stage on a date, and read its stage history (M4)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.viewer import Viewer
from app.db.models import Deal, DealStageEvent
from app.domain.enums import CLOSED_STAGES, DealStage
from app.services import deals
from app.services._common import require_deal, require_user
from app.services.errors import InvalidInputError
from app.services.textclean import scrub_optional


def _moment(on: date | None) -> datetime:
    """Today -> now; another day -> noon UTC of that day (a date has no time of day)."""
    now = datetime.now(UTC)
    if on is None or on == now.date():
        return now
    return datetime.combine(on, time(12, 0), tzinfo=UTC)


def move_stage(
    session: Session,
    ws_id: uuid.UUID,
    deal_id: uuid.UUID,
    stage: DealStage,
    *,
    on: date | None = None,
    lost_reason: str | None = None,
    changed_by_id: uuid.UUID | None = None,
    viewer: Viewer | None = None,
) -> Deal:
    """The rep's "Move to stage". `on` defaults to today; never in the future, never before the
    deal was created. Closing sets `closed_on` to that date; closed-lost keeps the reason."""
    deal = require_deal(session, ws_id, deal_id, viewer)
    today = datetime.now(UTC).date()
    when = on or today
    if when > today:
        raise InvalidInputError("the date cannot be in the future")
    if when < deal.created_on:
        raise InvalidInputError("the date is before the deal was created")
    if stage.value == deal.stage:
        raise InvalidInputError("the deal is already in this stage")
    if changed_by_id is not None:
        require_user(session, ws_id, changed_by_id)
    deals.set_stage(
        session,
        ws_id,
        deal_id,
        stage,
        when if stage in CLOSED_STAGES else None,
        changed_at=_moment(when),
        changed_by_id=changed_by_id,
    )
    if stage == DealStage.CLOSED_LOST:
        reason = scrub_optional(lost_reason)
        if reason and reason.strip():
            deal.lost_reason = reason.strip()[:500]
    session.flush()
    return deal


def list_events(
    session: Session, ws_id: uuid.UUID, deal_id: uuid.UUID, viewer: Viewer | None = None
) -> list[DealStageEvent]:
    """Oldest first."""
    require_deal(session, ws_id, deal_id, viewer)
    stmt = (
        select(DealStageEvent)
        .where(DealStageEvent.workspace_id == ws_id, DealStageEvent.deal_id == deal_id)
        .order_by(DealStageEvent.changed_at, DealStageEvent.created_at, DealStageEvent.id)
    )
    return list(session.scalars(stmt))
