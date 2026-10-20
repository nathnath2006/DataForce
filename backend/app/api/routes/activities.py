"""Activities (calls, emails, meetings) and tasks (M4)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from app.api.deps import CurrentViewer, CurrentWorkspace, Db
from app.api.schemas import Page
from app.api.schemas_activity import (
    ActivityCreate,
    ActivityOut,
    ActivityUpdate,
    ParticipantOut,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)
from app.db.models import Account, Activity, Deal, Task
from app.services import activities, tasks, users
from app.services._common import require_account, require_deal

router = APIRouter(tags=["activities"])

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


def _link_names(
    db: Db, deal_ids: list[uuid.UUID | None], account_ids: list[uuid.UUID | None]
) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, str]]:
    """({deal id: name}, {account id: name}) in two queries, for the cross-deal lists."""
    deals = {i for i in deal_ids if i}
    accounts = {i for i in account_ids if i}
    dn = (
        dict(db.execute(select(Deal.id, Deal.name).where(Deal.id.in_(deals))).all())
        if deals
        else {}
    )
    an = (
        dict(db.execute(select(Account.id, Account.name).where(Account.id.in_(accounts))).all())
        if accounts
        else {}
    )
    return dn, an


def _activities_out(db: Db, ws_id: uuid.UUID, rows: list[Activity]) -> list[ActivityOut]:
    dn, an = _link_names(db, [r.deal_id for r in rows], [r.account_id for r in rows])
    names = users.user_names(db, ws_id, [r.author_user_id for r in rows if r.author_user_id])
    people = activities.participants_of(db, ws_id, [r.id for r in rows])
    return [
        ActivityOut(
            id=r.id,
            account_id=r.account_id,
            deal_id=r.deal_id,
            kind=r.kind,
            direction=r.direction,
            occurred_at=r.occurred_at,
            subject=r.subject,
            body=r.body,
            source=r.source,
            author_id=r.author_user_id,
            author_name=names.get(r.author_user_id) if r.author_user_id else None,
            participants=[ParticipantOut(id=i, full_name=n) for i, n in people.get(r.id, [])],
            created_at=r.created_at,
            deal_name=dn.get(r.deal_id) if r.deal_id else None,
            account_name=an.get(r.account_id),
        )
        for r in rows
    ]


def _tasks_out(db: Db, ws_id: uuid.UUID, rows: list[Task]) -> list[TaskOut]:
    dn, an = _link_names(db, [r.deal_id for r in rows], [r.account_id for r in rows])
    names = users.user_names(db, ws_id, [r.owner_user_id for r in rows if r.owner_user_id])
    return [
        TaskOut(
            id=r.id,
            deal_id=r.deal_id,
            account_id=r.account_id,
            title=r.title,
            due_on=r.due_on,
            status=r.status,
            owner_id=r.owner_user_id,
            owner_name=names.get(r.owner_user_id) if r.owner_user_id else None,
            source=r.source,
            evidence=r.evidence or {},
            done_at=r.done_at,
            created_at=r.created_at,
            deal_name=dn.get(r.deal_id) if r.deal_id else None,
            account_name=an.get(r.account_id) if r.account_id else None,
        )
        for r in rows
    ]


# --- activities -----------------------------------------------------------------------------
@router.get("/w/{ws}/activities", response_model=Page[ActivityOut])
def list_all_activities(
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    kind: Annotated[str | None, Query(pattern="^(call|email|meeting|other)$")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: Literal["occurred_at", "kind", "subject"] | None = None,
    direction: Annotated[Literal["asc", "desc"], Query(alias="dir")] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Offset = 0,
) -> Page[ActivityOut]:
    rows, total = activities.list_activities_page(
        db,
        ws.id,
        kind=kind,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
        viewer=viewer,
    )
    return Page(items=_activities_out(db, ws.id, rows), total=total, offset=offset, limit=limit)


@router.get("/w/{ws}/accounts/{account_id}/activities", response_model=list[ActivityOut])
def list_account_activities(
    account_id: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    deal_id: uuid.UUID | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> list[ActivityOut]:
    rows = activities.list_activities(
        db, ws.id, account_id=account_id, deal_id=deal_id, limit=limit, offset=offset, viewer=viewer
    )
    return _activities_out(db, ws.id, rows)


@router.get("/w/{ws}/deals/{deal_id}/activities", response_model=list[ActivityOut])
def list_deal_activities(
    deal_id: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    limit: Limit = 100,
    offset: Offset = 0,
) -> list[ActivityOut]:
    rows = activities.list_activities(
        db, ws.id, deal_id=deal_id, limit=limit, offset=offset, viewer=viewer
    )
    return _activities_out(db, ws.id, rows)


@router.post(
    "/w/{ws}/accounts/{account_id}/activities", response_model=ActivityOut, status_code=201
)
def create_activity(
    account_id: uuid.UUID, body: ActivityCreate, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> ActivityOut:
    row = activities.create_activity(
        db,
        ws.id,
        account_id,
        kind=body.kind,
        direction=body.direction,
        occurred_at=body.occurred_at,
        subject=body.subject,
        body=body.body,
        deal_id=body.deal_id,
        participant_ids=body.participant_ids,
        author_user_id=viewer.app_user_id,
        viewer=viewer,
    )
    db.commit()
    return _activities_out(db, ws.id, [row])[0]


@router.get("/w/{ws}/activities/{activity_id}", response_model=ActivityOut)
def get_activity(
    activity_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> ActivityOut:
    return _activities_out(
        db, ws.id, [activities.require_activity(db, ws.id, activity_id, viewer)]
    )[0]


@router.patch("/w/{ws}/activities/{activity_id}", response_model=ActivityOut)
def update_activity(
    activity_id: uuid.UUID,
    body: ActivityUpdate,
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
) -> ActivityOut:
    row = activities.update_activity(
        db, ws.id, activity_id, body.model_dump(exclude_unset=True), viewer
    )
    db.commit()
    return _activities_out(db, ws.id, [row])[0]


@router.delete("/w/{ws}/activities/{activity_id}", status_code=204)
def delete_activity(
    activity_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> Response:
    activities.delete_activity(db, ws.id, activity_id, viewer)
    db.commit()
    return Response(status_code=204)


# --- tasks ----------------------------------------------------------------------------------
@router.get("/w/{ws}/tasks", response_model=Page[TaskOut])
def list_tasks(
    db: Db,
    ws: CurrentWorkspace,
    viewer: CurrentViewer,
    deal_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    status: Annotated[str | None, Query(pattern="^(suggested|open|done|dismissed)$")] = None,
    due: Annotated[str | None, Query(pattern="^(overdue|this_week|later|none)$")] = None,
    sort: Literal["due_on", "title", "status", "created_at"] | None = None,
    direction: Annotated[Literal["asc", "desc"], Query(alias="dir")] = "asc",
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[TaskOut]:
    if deal_id is not None:
        require_deal(db, ws.id, deal_id, viewer)
    if account_id is not None:
        require_account(db, ws.id, account_id, viewer)
    rows, total = tasks.list_tasks_page(
        db,
        ws.id,
        deal_id=deal_id,
        account_id=account_id,
        owner_user_id=owner_id,
        status=status,
        due=due,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
        viewer=viewer,
    )
    return Page(items=_tasks_out(db, ws.id, rows), total=total, offset=offset, limit=limit)


@router.get("/w/{ws}/deals/{deal_id}/tasks", response_model=list[TaskOut])
def list_deal_tasks(
    deal_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> list[TaskOut]:
    return _tasks_out(db, ws.id, tasks.list_tasks(db, ws.id, deal_id=deal_id, viewer=viewer))


@router.get("/w/{ws}/accounts/{account_id}/tasks", response_model=list[TaskOut])
def list_account_tasks(
    account_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> list[TaskOut]:
    return _tasks_out(db, ws.id, tasks.list_tasks(db, ws.id, account_id=account_id, viewer=viewer))


@router.post("/w/{ws}/tasks", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer) -> TaskOut:
    row = tasks.create_task(
        db,
        ws.id,
        title=body.title,
        deal_id=body.deal_id,
        account_id=body.account_id,
        due_on=body.due_on,
        owner_user_id=viewer.app_user_id,
        viewer=viewer,
    )
    db.commit()
    return _tasks_out(db, ws.id, [row])[0]


@router.patch("/w/{ws}/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task_id: uuid.UUID, body: TaskUpdate, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> TaskOut:
    changes = body.model_dump(exclude_unset=True)
    if "owner_id" in changes:
        changes["owner_user_id"] = changes.pop("owner_id")
    row = tasks.update_task(db, ws.id, task_id, changes, viewer)
    db.commit()
    return _tasks_out(db, ws.id, [row])[0]


@router.post("/w/{ws}/tasks/{task_id}/accept", response_model=TaskOut)
def accept_task(task_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer) -> TaskOut:
    row = tasks.accept_task(db, ws.id, task_id, viewer)
    db.commit()
    return _tasks_out(db, ws.id, [row])[0]


@router.delete("/w/{ws}/tasks/{task_id}", status_code=204)
def delete_task(
    task_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> Response:
    tasks.delete_task(db, ws.id, task_id, viewer)
    db.commit()
    return Response(status_code=204)
