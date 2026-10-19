"""Deals."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Account, AppUser, Deal, DealStageEvent
from app.domain.enums import CLOSED_STAGES, DealStage
from app.domain.schemas import DealIn
from app.services._common import (
    LIKE_ESCAPE,
    get_scoped,
    like_contains,
    require_account,
    require_deal,
    require_user,
)
from app.services.errors import InvalidInputError
from app.services.textclean import scrub_optional, scrub_text


def _check_dates(created_on: date, closed_on: date | None) -> None:
    if closed_on is not None and closed_on < created_on:
        raise InvalidInputError("closed_on is before created_on")


def create_deal(session: Session, ws_id: uuid.UUID, data: DealIn) -> Deal:
    require_account(session, ws_id, data.account_id)
    if data.owner_id is not None:
        require_user(session, ws_id, data.owner_id)
    _check_dates(data.created_on, data.closed_on)
    # A closed stage without closed_on is accepted on purpose: real CRM data is like that.
    deal = Deal(
        workspace_id=ws_id,
        account_id=data.account_id,
        owner_id=data.owner_id,
        name=scrub_text(data.name),
        amount_eur=data.amount_eur,
        stage=data.stage.value,
        lead_source=data.lead_source.value if data.lead_source else None,
        created_on=data.created_on,
        closed_on=data.closed_on,
        lost_reason=scrub_optional(data.lost_reason),
        source=data.source.value,
    )
    session.add(deal)
    session.flush()
    return deal


def get_deal(session: Session, ws_id: uuid.UUID, deal_id: uuid.UUID) -> Deal | None:
    return get_scoped(session, Deal, ws_id, deal_id)


def list_deals(session: Session, ws_id: uuid.UUID) -> list[Deal]:
    stmt = select(Deal).where(Deal.workspace_id == ws_id).order_by(Deal.created_on, Deal.id)
    return list(session.scalars(stmt))


def set_stage(
    session: Session,
    ws_id: uuid.UUID,
    deal_id: uuid.UUID,
    stage: DealStage,
    closed_on: date | None = None,
    *,
    changed_at: datetime | None = None,
    changed_by_id: uuid.UUID | None = None,
    source: str = "manual",
) -> Deal:
    """Move a deal. Reopening clears closed_on; closing with closed_on=None keeps any existing
    date (and leaves it missing otherwise). Every real stage change is recorded as a
    DealStageEvent, whichever path called this (M4)."""
    deal = require_deal(session, ws_id, deal_id)
    previous = deal.stage
    if stage in CLOSED_STAGES:
        if closed_on is not None:
            _check_dates(deal.created_on, closed_on)
            deal.closed_on = closed_on
    else:
        deal.closed_on = None
    deal.stage = stage.value
    if previous != stage.value:
        session.add(
            DealStageEvent(
                workspace_id=ws_id,
                deal_id=deal.id,
                from_stage=previous,
                to_stage=stage.value,
                changed_at=changed_at or datetime.now(UTC),
                changed_by_id=changed_by_id,
                source=source,
            )
        )
    session.flush()
    return deal


_UPDATABLE = ("owner_id", "name", "amount_eur", "lead_source", "created_on", "lost_reason")


def update_deal(
    session: Session, ws_id: uuid.UUID, deal_id: uuid.UUID, changes: dict[str, Any]
) -> Deal:
    """Partial update (the stage has `set_stage`). The owner must belong to the workspace and
    the dates stay consistent."""
    deal = require_deal(session, ws_id, deal_id)
    unknown = set(changes) - set(_UPDATABLE)
    if unknown:
        raise InvalidInputError(f"cannot update: {', '.join(sorted(unknown))}")
    if "owner_id" in changes and changes["owner_id"] is not None:
        require_user(session, ws_id, changes["owner_id"])
    if "name" in changes:
        name = scrub_text(changes["name"]).strip() if changes["name"] else ""
        if not name:
            raise InvalidInputError("name cannot be empty")
        changes = {**changes, "name": name}
    if "created_on" in changes:
        if changes["created_on"] is None:
            raise InvalidInputError("created_on cannot be cleared")
        _check_dates(changes["created_on"], deal.closed_on)
    for key, value in changes.items():
        if key == "lead_source" and value is not None:
            value = getattr(value, "value", value)
        elif key == "lost_reason":
            value = scrub_optional(value)
        setattr(deal, key, value)
    session.flush()
    return deal


def delete_deal(session: Session, ws_id: uuid.UUID, deal_id: uuid.UUID) -> None:
    session.delete(require_deal(session, ws_id, deal_id))
    session.flush()


def list_deals_page(
    session: Session,
    ws_id: uuid.UUID,
    *,
    account_id: uuid.UUID | None = None,
    stage: str | None = None,
    lead_source: str | None = None,
    owner_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[Deal], int]:
    """Newest `created_on` first. `q` is a literal case-insensitive substring of the name."""
    cond = [Deal.workspace_id == ws_id]
    if account_id is not None:
        cond.append(Deal.account_id == account_id)
    if stage:
        cond.append(Deal.stage == stage)
    if lead_source:
        cond.append(Deal.lead_source == lead_source)
    if owner_id is not None:
        cond.append(Deal.owner_id == owner_id)
    if q:
        cond.append(Deal.name.ilike(like_contains(q), escape=LIKE_ESCAPE))
    total = session.scalar(select(func.count()).select_from(Deal).where(*cond)) or 0
    stmt = select(Deal).where(*cond).order_by(Deal.created_on.desc(), Deal.id)
    return list(session.scalars(stmt.limit(limit).offset(offset))), total


def deal_names(
    session: Session, ws_id: uuid.UUID, deal_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, str | None]]:
    """{deal id: (account name, owner name or None)} in one query."""
    if not deal_ids:
        return {}
    rows = session.execute(
        select(Deal.id, Account.name, AppUser.display_name)
        .join(Account, Account.id == Deal.account_id)
        .outerjoin(AppUser, AppUser.id == Deal.owner_id)
        .where(Deal.workspace_id == ws_id, Deal.id.in_(deal_ids))
    )
    return {did: (acc, owner) for did, acc, owner in rows}
