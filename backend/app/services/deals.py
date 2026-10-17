"""Deals."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Deal
from app.domain.enums import CLOSED_STAGES, DealStage
from app.domain.schemas import DealIn
from app.services._common import get_scoped, require_account, require_deal, require_user
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
) -> Deal:
    """Move a deal. Reopening clears closed_on; closing with closed_on=None keeps any existing
    date (and leaves it missing otherwise)."""
    deal = require_deal(session, ws_id, deal_id)
    if stage in CLOSED_STAGES:
        if closed_on is not None:
            _check_dates(deal.created_on, closed_on)
            deal.closed_on = closed_on
    else:
        deal.closed_on = None
    deal.stage = stage.value
    session.flush()
    return deal
