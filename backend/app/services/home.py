"""The Home dashboard: exact numbers over the rows the viewer may see (SQL aggregates, no
sampling). With `owner`, the admin and *see all* members see one rep's numbers instead."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from app.api.schemas_home import (
    HomeActivity,
    HomeDeal,
    HomeKpis,
    HomeOut,
    HomeStage,
    HomeStalledDeal,
    HomeTask,
)
from app.auth import visibility
from app.auth.viewer import Viewer
from app.db.models import Account, Activity, AppUser, Deal, DealStageEvent, Task
from app.domain.enums import OPEN_STAGES, DealStage
from app.services.tasks import week_end

LIST_SIZE = 10
TOP_SIZE = 5
STALL_DAYS = 30  # an open deal without a stage change for this long is stalling
_OPEN = [s.value for s in OPEN_STAGES]


def quarter_start(today: date) -> date:
    return date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)


def _deals(ws_id: uuid.UUID, viewer: Viewer) -> Select:
    return select(Deal).where(
        Deal.workspace_id == ws_id, *visibility.conds(visibility.deals_cond(viewer))
    )


def _tasks_cond(ws_id: uuid.UUID, viewer: Viewer) -> list:
    return [
        Task.workspace_id == ws_id,
        *visibility.conds(visibility.account_or_deal(viewer, Task.account_id, Task.deal_id)),
    ]


def _kpis(db: Session, ws_id: uuid.UUID, viewer: Viewer, today: date) -> HomeKpis:
    deal_cond = [Deal.workspace_id == ws_id, *visibility.conds(visibility.deals_cond(viewer))]
    is_open = Deal.stage.in_(_OPEN)
    won = (Deal.stage == "closed_won") & (Deal.closed_on >= quarter_start(today))
    n_open, pipeline, n_won, won_eur = db.execute(
        select(
            func.coalesce(func.sum(case((is_open, 1), else_=0)), 0),
            func.coalesce(func.sum(case((is_open, Deal.amount_eur), else_=0)), 0),
            func.coalesce(func.sum(case((won, 1), else_=0)), 0),
            func.coalesce(func.sum(case((won, Deal.amount_eur), else_=0)), 0),
        ).where(*deal_cond)
    ).one()
    t_cond = _tasks_cond(ws_id, viewer)
    is_task_open = Task.status.in_(("open", "in_progress"))
    due_week, overdue = db.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            is_task_open
                            & (Task.due_on >= today)
                            & (Task.due_on <= week_end(today)),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(func.sum(case((is_task_open & (Task.due_on < today), 1), else_=0)), 0),
        ).where(*t_cond)
    ).one()
    return HomeKpis(
        open_deals=int(n_open),
        open_pipeline_eur=pipeline,
        won_this_quarter=int(n_won),
        won_this_quarter_eur=won_eur,
        tasks_due_week=int(due_week),
        tasks_overdue=int(overdue),
    )


def _deal_out(d: Deal, account: str, owner: str | None) -> HomeDeal:
    return HomeDeal(
        id=d.id,
        name=d.name,
        account_id=d.account_id,
        account_name=account,
        stage=d.stage,
        amount_eur=d.amount_eur,
        created_on=d.created_on,
        owner_name=owner,
    )


def _top_deals(db: Session, ws_id: uuid.UUID, viewer: Viewer) -> list[HomeDeal]:
    """The biggest open deals (a deal without an amount comes last)."""
    rows = db.execute(
        select(Deal, Account.name, AppUser.display_name)
        .join(Account, Account.id == Deal.account_id)
        .outerjoin(AppUser, AppUser.id == Deal.owner_id)
        .where(
            Deal.workspace_id == ws_id,
            Deal.stage.in_(_OPEN),
            *visibility.conds(visibility.deals_cond(viewer)),
        )
        .order_by(Deal.amount_eur.desc().nulls_last(), Deal.id)
        .limit(TOP_SIZE)
    ).all()
    return [_deal_out(d, a, o) for d, a, o in rows]


def _stalled_deals(
    db: Session, ws_id: uuid.UUID, viewer: Viewer, today: date
) -> tuple[list[HomeStalledDeal], int]:
    """Open deals whose stage has not moved for STALL_DAYS days or more, the oldest first."""
    last = (
        select(DealStageEvent.deal_id, func.max(DealStageEvent.changed_at).label("at"))
        .where(DealStageEvent.workspace_id == ws_id)
        .group_by(DealStageEvent.deal_id)
        .subquery()
    )
    since = func.coalesce(func.date(last.c.at), Deal.created_on)
    cond = [
        Deal.workspace_id == ws_id,
        Deal.stage.in_(_OPEN),
        *visibility.conds(visibility.deals_cond(viewer)),
        since <= today - timedelta(days=STALL_DAYS),
    ]
    total = db.scalar(
        select(func.count(Deal.id)).outerjoin(last, last.c.deal_id == Deal.id).where(*cond)
    )
    rows = db.execute(
        select(Deal, Account.name, AppUser.display_name, since.label("since"))
        .join(Account, Account.id == Deal.account_id)
        .outerjoin(AppUser, AppUser.id == Deal.owner_id)
        .outerjoin(last, last.c.deal_id == Deal.id)
        .where(*cond)
        .order_by(since.asc(), Deal.id)
        .limit(TOP_SIZE)
    ).all()
    return [
        HomeStalledDeal(**_deal_out(d, a, o).model_dump(), days_in_stage=(today - since_day).days)
        for d, a, o, since_day in rows
    ], int(total or 0)


def _by_stage(db: Session, ws_id: uuid.UUID, viewer: Viewer) -> list[HomeStage]:
    rows = {
        stage: (int(n), amount)
        for stage, n, amount in db.execute(
            select(Deal.stage, func.count(Deal.id), func.coalesce(func.sum(Deal.amount_eur), 0))
            .where(Deal.workspace_id == ws_id, *visibility.conds(visibility.deals_cond(viewer)))
            .group_by(Deal.stage)
        )
    }
    return [
        HomeStage(
            stage=s.value,
            count=rows.get(s.value, (0, 0))[0],
            amount_eur=rows.get(s.value, (0, 0))[1],
        )
        for s in DealStage
    ]


def _open_deals(db: Session, ws_id: uuid.UUID, viewer: Viewer) -> list[HomeDeal]:
    rows = db.execute(
        select(Deal, Account.name, AppUser.display_name)
        .join(Account, Account.id == Deal.account_id)
        .outerjoin(AppUser, AppUser.id == Deal.owner_id)
        .where(
            Deal.workspace_id == ws_id,
            Deal.stage.in_(_OPEN),
            *visibility.conds(visibility.deals_cond(viewer)),
        )
        .order_by(Deal.created_on.desc(), Deal.id)
        .limit(LIST_SIZE)
    ).all()
    return [
        HomeDeal(
            id=d.id,
            name=d.name,
            account_id=d.account_id,
            account_name=account,
            stage=d.stage,
            amount_eur=d.amount_eur,
            created_on=d.created_on,
            owner_name=owner,
        )
        for d, account, owner in rows
    ]


def _tasks(db: Session, ws_id: uuid.UUID, viewer: Viewer, today: date) -> list[HomeTask]:
    """Open tasks due by Sunday, overdue first, then the soonest."""
    rows = db.execute(
        select(Task, Deal.name, Account.name)
        .outerjoin(Deal, Deal.id == Task.deal_id)
        .outerjoin(Account, Account.id == Task.account_id)
        .where(
            *_tasks_cond(ws_id, viewer),
            Task.status.in_(("open", "in_progress")),
            Task.due_on <= week_end(today),
        )
        .order_by(Task.due_on.asc(), Task.created_at, Task.id)
        .limit(LIST_SIZE)
    ).all()
    return [
        HomeTask(
            id=t.id,
            title=t.title,
            due_on=t.due_on,
            status=t.status,
            overdue=t.due_on is not None and t.due_on < today,
            deal_id=t.deal_id,
            deal_name=deal,
            account_id=t.account_id,
            account_name=account,
        )
        for t, deal, account in rows
    ]


def _activity(db: Session, ws_id: uuid.UUID, viewer: Viewer) -> list[HomeActivity]:
    """The last timeline items (stage moves, activities, tasks) across the visible deals."""
    deals = select(Deal.id).where(
        Deal.workspace_id == ws_id, *visibility.conds(visibility.deals_cond(viewer))
    )
    names = Deal.name
    items: list[HomeActivity] = []
    for ev, name in db.execute(
        select(DealStageEvent, names)
        .join(Deal, Deal.id == DealStageEvent.deal_id)
        .where(DealStageEvent.workspace_id == ws_id, DealStageEvent.deal_id.in_(deals))
        .order_by(DealStageEvent.changed_at.desc())
        .limit(LIST_SIZE)
    ):
        label = f"{(ev.from_stage or 'new').replace('_', ' ')} → {ev.to_stage.replace('_', ' ')}"
        items.append(
            HomeActivity(
                id=f"stage:{ev.id}", kind="stage", at=ev.changed_at, title=f"Stage: {label}",
                author_name=None, deal_id=ev.deal_id, deal_name=name,
            )
        )  # fmt: skip
    for a, name, author in db.execute(
        select(Activity, names, AppUser.display_name)
        .join(Deal, Deal.id == Activity.deal_id)
        .outerjoin(AppUser, AppUser.id == Activity.author_user_id)
        .where(Activity.workspace_id == ws_id, Activity.deal_id.in_(deals))
        .order_by(Activity.occurred_at.desc())
        .limit(LIST_SIZE)
    ):
        kind = a.kind if a.kind in ("call", "email", "meeting") else "other"
        items.append(
            HomeActivity(
                id=f"activity:{a.id}", kind=kind, at=a.occurred_at, title=a.subject,
                author_name=author, deal_id=a.deal_id, deal_name=name,
            )
        )  # fmt: skip
    for t, name, owner in db.execute(
        select(Task, names, AppUser.display_name)
        .join(Deal, Deal.id == Task.deal_id)
        .outerjoin(AppUser, AppUser.id == Task.owner_user_id)
        .where(Task.workspace_id == ws_id, Task.deal_id.in_(deals))
        .order_by(func.coalesce(Task.done_at, Task.created_at).desc())
        .limit(LIST_SIZE)
    ):
        verb = {
            "done": "done",
            "dismissed": "dismissed",
            "suggested": "suggested",
            "in_progress": "in progress",
        }.get(t.status, "open")
        items.append(
            HomeActivity(
                id=f"task:{t.id}", kind="task", at=t.done_at or t.created_at,
                title=f"Task {verb}: {t.title}", author_name=owner,
                deal_id=t.deal_id, deal_name=name,  # type: ignore[arg-type]
            )
        )  # fmt: skip
    items.sort(key=lambda i: (i.at, i.id), reverse=True)
    return items[:LIST_SIZE]


def home(
    db: Session,
    ws_id: uuid.UUID,
    viewer: Viewer,
    owner_id: uuid.UUID | None = None,
    today: date | None = None,
) -> HomeOut:
    """403 for `owner_id` unless the viewer is the admin or sees everything."""
    eff = visibility.scoped_viewer(db, viewer, owner_id)
    today = today or datetime.now(UTC).date()
    stalled, stalled_total = _stalled_deals(db, ws_id, eff, today)
    return HomeOut(
        kpis=_kpis(db, ws_id, eff, today),
        open_deals=_open_deals(db, ws_id, eff),
        top_deals=_top_deals(db, ws_id, eff),
        stalled_deals=stalled,
        stalled_total=stalled_total,
        by_stage=_by_stage(db, ws_id, eff),
        tasks=_tasks(db, ws_id, eff, today),
        activity=_activity(db, ws_id, eff),
    )
