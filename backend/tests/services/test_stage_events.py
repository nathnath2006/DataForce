"""Stage control, stage history and the demo backfill (M4)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Activity, DealStageEvent, Task
from app.demo.activities import backfill_workspace
from app.domain.enums import DealStage
from app.domain.schemas import AccountIn, ContactIn, DealIn, UserIn
from app.services import accounts, contacts, deals, stage_events, users, workspaces
from app.services.errors import InvalidInputError

pytestmark = pytest.mark.integration

TODAY = datetime.now(UTC).date()


def _deal(s: Session, ws, created=None, stage=DealStage.PROSPECTING, closed_on=None):
    acc = accounts.create_account(s, ws.id, AccountIn(name="Acme"))
    return deals.create_deal(
        s,
        ws.id,
        DealIn(
            account_id=acc.id,
            name="D",
            stage=stage,
            created_on=created or TODAY - timedelta(days=60),
            closed_on=closed_on,
        ),
    )


@pytest.fixture
def ws(db_session: Session):
    return workspaces.create_workspace(db_session, "se", "SE", is_demo=True)


def test_move_records_event_with_author_and_date(db_session: Session, ws):
    s = db_session
    user = users.create_user(s, ws.id, UserIn(display_name="Ann"))
    d = _deal(s, ws)
    on = TODAY - timedelta(days=10)
    stage_events.move_stage(s, ws.id, d.id, DealStage.QUALIFICATION, on=on, changed_by_id=user.id)
    ev = stage_events.list_events(s, ws.id, d.id)
    assert len(ev) == 1
    assert (ev[0].from_stage, ev[0].to_stage) == ("prospecting", "qualification")
    assert ev[0].changed_at.date() == on and ev[0].changed_by_id == user.id
    assert d.stage == "qualification" and d.closed_on is None


def test_close_sets_closed_on_and_reopen_clears(db_session: Session, ws):
    s = db_session
    d = _deal(s, ws)
    on = TODAY - timedelta(days=3)
    stage_events.move_stage(s, ws.id, d.id, DealStage.CLOSED_LOST, on=on, lost_reason="Budget")
    assert d.closed_on == on and d.lost_reason == "Budget"
    stage_events.move_stage(s, ws.id, d.id, DealStage.NEGOTIATION)
    assert d.closed_on is None
    assert [e.to_stage for e in stage_events.list_events(s, ws.id, d.id)] == [
        "closed_lost",
        "negotiation",
    ]


def test_date_rules(db_session: Session, ws):
    s = db_session
    d = _deal(s, ws, created=TODAY - timedelta(days=5))
    with pytest.raises(InvalidInputError):  # future
        stage_events.move_stage(s, ws.id, d.id, DealStage.PROPOSAL, on=TODAY + timedelta(days=1))
    with pytest.raises(InvalidInputError):  # before created_on
        stage_events.move_stage(s, ws.id, d.id, DealStage.PROPOSAL, on=TODAY - timedelta(days=6))
    with pytest.raises(InvalidInputError):  # same stage
        stage_events.move_stage(s, ws.id, d.id, DealStage.PROSPECTING)
    assert stage_events.list_events(s, ws.id, d.id) == []


def test_other_path_records_event(db_session: Session, ws):
    """deals.set_stage (the old PUT route) records too; a no-op does not."""
    s = db_session
    d = _deal(s, ws)
    deals.set_stage(s, ws.id, d.id, DealStage.PROPOSAL)
    deals.set_stage(s, ws.id, d.id, DealStage.PROPOSAL)
    assert len(stage_events.list_events(s, ws.id, d.id)) == 1


def test_backfill_idempotent_and_consistent(db_session: Session, ws):
    s = db_session
    acc = accounts.create_account(s, ws.id, AccountIn(name="Beta"))
    contacts.create_contact(s, ws.id, ContactIn(account_id=acc.id, full_name="Zoe Martin"))
    mk = lambda name, stage, closed: deals.create_deal(  # noqa: E731
        s,
        ws.id,
        DealIn(
            account_id=acc.id,
            name=name,
            stage=stage,
            created_on=TODAY - timedelta(days=90),
            closed_on=closed,
        ),
    )
    open_d = mk("open", DealStage.PROPOSAL, None)
    won = mk("won", DealStage.CLOSED_WON, TODAY - timedelta(days=20))
    lost = mk("lost", DealStage.CLOSED_LOST, TODAY - timedelta(days=30))
    first = backfill_workspace(s, "se")
    assert first["deals"] == 3 and first["activities"] >= 6
    n_events = s.scalar(select(func.count()).select_from(DealStageEvent))
    n_act = s.scalar(select(func.count()).select_from(Activity))
    second = backfill_workspace(s, "se")
    assert second["deals"] == 0 and second["skipped"] == 3
    assert s.scalar(select(func.count()).select_from(DealStageEvent)) == n_events
    assert s.scalar(select(func.count()).select_from(Activity)) == n_act
    s.scalar(select(func.count()).select_from(Task))
    for d in (open_d, won, lost):
        ev = stage_events.list_events(s, ws.id, d.id)
        assert ev[0].from_stage is None and ev[-1].to_stage == d.stage
        assert all(a.to_stage == b.from_stage for a, b in zip(ev, ev[1:], strict=False))  # a chain
        times = [e.changed_at for e in ev]
        assert times == sorted(times)
        assert times[0].date() >= d.created_on and times[-1] <= datetime.now(UTC)
        if d.closed_on:
            assert ev[-1].changed_at.date() == d.closed_on
    acts = list(s.scalars(select(Activity).where(Activity.workspace_id == ws.id)))
    assert all(a.source == "demo" and a.occurred_at <= datetime.now(UTC) for a in acts)


def test_backfill_refuses_non_demo(db_session: Session):
    workspaces.create_workspace(db_session, "real", "Real", is_demo=False)
    with pytest.raises(InvalidInputError):
        backfill_workspace(db_session, "real")
    with pytest.raises(InvalidInputError):
        backfill_workspace(db_session, "missing")


def test_date_type_unused():
    assert isinstance(TODAY, date)
