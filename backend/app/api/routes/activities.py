"""Activities (calls, emails, meetings) and tasks (M4)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.deps import CurrentWorkspace, Db
from app.api.schemas_activity import (
    ActivityCreate,
    ActivityOut,
    ActivityUpdate,
    ParticipantOut,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)
from app.db.models import Activity, Task
from app.services import activities, tasks, users
from app.services._common import require_account, require_deal

router = APIRouter(tags=["activities"])

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


def _activities_out(db: Db, ws_id: uuid.UUID, rows: list[Activity]) -> list[ActivityOut]:
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
        )
        for r in rows
    ]


def _tasks_out(db: Db, ws_id: uuid.UUID, rows: list[Task]) -> list[TaskOut]:
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
        )
        for r in rows
    ]


# --- activities -----------------------------------------------------------------------------
@router.get("/w/{ws}/accounts/{account_id}/activities", response_model=list[ActivityOut])
def list_account_activities(
    account_id: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    deal_id: uuid.UUID | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> list[ActivityOut]:
    rows = activities.list_activities(
        db, ws.id, account_id=account_id, deal_id=deal_id, limit=limit, offset=offset
    )
    return _activities_out(db, ws.id, rows)


@router.get("/w/{ws}/deals/{deal_id}/activities", response_model=list[ActivityOut])
def list_deal_activities(
    deal_id: uuid.UUID, db: Db, ws: CurrentWorkspace, limit: Limit = 100, offset: Offset = 0
) -> list[ActivityOut]:
    rows = activities.list_activities(db, ws.id, deal_id=deal_id, limit=limit, offset=offset)
    return _activities_out(db, ws.id, rows)


@router.post(
    "/w/{ws}/accounts/{account_id}/activities", response_model=ActivityOut, status_code=201
)
def create_activity(
    account_id: uuid.UUID, body: ActivityCreate, db: Db, ws: CurrentWorkspace
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
        author_user_id=body.author_id,
    )
    db.commit()
    return _activities_out(db, ws.id, [row])[0]


@router.get("/w/{ws}/activities/{activity_id}", response_model=ActivityOut)
def get_activity(activity_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> ActivityOut:
    return _activities_out(db, ws.id, [activities.require_activity(db, ws.id, activity_id)])[0]


@router.patch("/w/{ws}/activities/{activity_id}", response_model=ActivityOut)
def update_activity(
    activity_id: uuid.UUID, body: ActivityUpdate, db: Db, ws: CurrentWorkspace
) -> ActivityOut:
    row = activities.update_activity(db, ws.id, activity_id, body.model_dump(exclude_unset=True))
    db.commit()
    return _activities_out(db, ws.id, [row])[0]


@router.delete("/w/{ws}/activities/{activity_id}", status_code=204)
def delete_activity(activity_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> Response:
    activities.delete_activity(db, ws.id, activity_id)
    db.commit()
    return Response(status_code=204)


# --- tasks ----------------------------------------------------------------------------------
@router.get("/w/{ws}/tasks", response_model=list[TaskOut])
def list_tasks(
    db: Db,
    ws: CurrentWorkspace,
    deal_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    status: Annotated[str | None, Query(pattern="^(suggested|open|done|dismissed)$")] = None,
    limit: Limit = 200,
    offset: Offset = 0,
) -> list[TaskOut]:
    rows = tasks.list_tasks(
        db,
        ws.id,
        deal_id=deal_id,
        account_id=account_id,
        owner_user_id=owner_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return _tasks_out(db, ws.id, rows)


@router.get("/w/{ws}/deals/{deal_id}/tasks", response_model=list[TaskOut])
def list_deal_tasks(deal_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> list[TaskOut]:
    require_deal(db, ws.id, deal_id)
    return _tasks_out(db, ws.id, tasks.list_tasks(db, ws.id, deal_id=deal_id))


@router.get("/w/{ws}/accounts/{account_id}/tasks", response_model=list[TaskOut])
def list_account_tasks(account_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> list[TaskOut]:
    require_account(db, ws.id, account_id)
    return _tasks_out(db, ws.id, tasks.list_tasks(db, ws.id, account_id=account_id))


@router.post("/w/{ws}/tasks", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, db: Db, ws: CurrentWorkspace) -> TaskOut:
    row = tasks.create_task(
        db,
        ws.id,
        title=body.title,
        deal_id=body.deal_id,
        account_id=body.account_id,
        due_on=body.due_on,
        owner_user_id=body.owner_id,
    )
    db.commit()
    return _tasks_out(db, ws.id, [row])[0]


@router.patch("/w/{ws}/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: uuid.UUID, body: TaskUpdate, db: Db, ws: CurrentWorkspace) -> TaskOut:
    changes = body.model_dump(exclude_unset=True)
    if "owner_id" in changes:
        changes["owner_user_id"] = changes.pop("owner_id")
    row = tasks.update_task(db, ws.id, task_id, changes)
    db.commit()
    return _tasks_out(db, ws.id, [row])[0]


@router.post("/w/{ws}/tasks/{task_id}/accept", response_model=TaskOut)
def accept_task(task_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> TaskOut:
    row = tasks.accept_task(db, ws.id, task_id)
    db.commit()
    return _tasks_out(db, ws.id, [row])[0]


@router.delete("/w/{ws}/tasks/{task_id}", status_code=204)
def delete_task(task_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> Response:
    tasks.delete_task(db, ws.id, task_id)
    db.commit()
    return Response(status_code=204)
