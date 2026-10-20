"""Tasks on a deal or an account (M4). `suggested` is reserved for AI and becomes `open` only
through `accept_task`, a person's decision."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.auth import visibility
from app.auth.viewer import Viewer
from app.db.models import Task
from app.services._common import (
    order_clauses,
    require,
    require_account,
    require_deal,
    require_user,
)
from app.services.errors import ForbiddenError, InvalidInputError
from app.services.textclean import scrub_text

TITLE_MAX = 300
SETTABLE = ("open", "done", "dismissed")
_UPDATABLE = {"title", "due_on", "status", "owner_user_id"}


def _title(title: str) -> str:
    title = scrub_text(title).strip()
    if not title:
        raise InvalidInputError("title cannot be empty")
    if len(title) > TITLE_MAX:
        raise InvalidInputError(f"title is longer than {TITLE_MAX} characters")
    return title


def create_task(
    session: Session,
    ws_id: uuid.UUID,
    *,
    title: str,
    deal_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    due_on: date | None = None,
    owner_user_id: uuid.UUID | None = None,
    source: str = "manual",
    viewer: Viewer | None = None,
) -> Task:
    if deal_id is None and account_id is None:
        raise InvalidInputError("a task needs a deal or an account")
    if deal_id is not None:
        deal = require_deal(session, ws_id, deal_id, viewer)
        if account_id is not None and account_id != deal.account_id:
            raise InvalidInputError("the deal belongs to another account")
        account_id = deal.account_id
    else:
        require_account(session, ws_id, account_id, viewer)  # type: ignore[arg-type]
    if owner_user_id is not None:
        require_user(session, ws_id, owner_user_id)
    row = Task(
        workspace_id=ws_id,
        deal_id=deal_id,
        account_id=account_id,
        title=_title(title),
        due_on=due_on,
        status="open",
        owner_user_id=owner_user_id,
        source=source,
        evidence={},
    )
    session.add(row)
    session.flush()
    return row


def require_task(
    session: Session, ws_id: uuid.UUID, task_id: uuid.UUID, viewer: Viewer | None = None
) -> Task:
    row = require(session, Task, ws_id, task_id)
    visibility.check_row_account(session, viewer, row.account_id, row.deal_id)
    return row


def update_task(
    session: Session,
    ws_id: uuid.UUID,
    task_id: uuid.UUID,
    changes: dict[str, Any],
    viewer: Viewer | None = None,
) -> Task:
    row = require_task(session, ws_id, task_id, viewer)
    if viewer is not None and "owner_user_id" in changes:
        if changes["owner_user_id"] != row.owner_user_id and not viewer.is_admin:
            raise ForbiddenError("only the administrator can reassign a task")
    unknown = set(changes) - _UPDATABLE
    if unknown:
        raise InvalidInputError(f"cannot update: {', '.join(sorted(unknown))}")
    if "title" in changes:
        row.title = _title(changes["title"] or "")
    if "due_on" in changes:
        row.due_on = changes["due_on"]
    if changes.get("owner_user_id") is not None:
        require_user(session, ws_id, changes["owner_user_id"])
    if "owner_user_id" in changes:
        row.owner_user_id = changes["owner_user_id"]
    if "status" in changes:
        status = changes["status"]
        if status not in SETTABLE:
            raise InvalidInputError(
                "status must be open, done or dismissed (suggestions are accepted, not set)"
            )
        if row.status == "suggested" and status == "open":
            raise InvalidInputError("accept a suggested task instead")
        row.done_at = datetime.now(UTC) if status == "done" else None
        row.status = status
    session.flush()
    return row


def accept_task(
    session: Session, ws_id: uuid.UUID, task_id: uuid.UUID, viewer: Viewer | None = None
) -> Task:
    row = require_task(session, ws_id, task_id, viewer)
    if row.status != "suggested":
        raise InvalidInputError("only a suggested task can be accepted")
    row.status = "open"
    session.flush()
    return row


def delete_task(
    session: Session, ws_id: uuid.UUID, task_id: uuid.UUID, viewer: Viewer | None = None
) -> None:
    row = require_task(session, ws_id, task_id, viewer)
    if viewer is not None:
        visibility.require_delete(viewer, row.owner_user_id)
    session.delete(row)
    session.flush()


def list_tasks(
    session: Session,
    ws_id: uuid.UUID,
    *,
    deal_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    owner_user_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
    viewer: Viewer | None = None,
) -> list[Task]:
    """Open first (then suggested, done, dismissed), earliest due date first."""
    stmt = select(Task).where(
        Task.workspace_id == ws_id,
        *visibility.conds(visibility.account_or_deal(viewer, Task.account_id, Task.deal_id)),
    )
    if deal_id is not None:
        require_deal(session, ws_id, deal_id, viewer)
        stmt = stmt.where(Task.deal_id == deal_id)
    if account_id is not None:
        require_account(session, ws_id, account_id, viewer)
        stmt = stmt.where(Task.account_id == account_id)
    if owner_user_id is not None:
        stmt = stmt.where(Task.owner_user_id == owner_user_id)
    if status:
        stmt = stmt.where(Task.status == status)
    rank = case(
        (Task.status == "open", 0),
        (Task.status == "suggested", 1),
        (Task.status == "done", 2),
        else_=3,
    )
    stmt = stmt.order_by(rank, Task.due_on.asc().nulls_last(), Task.created_at.desc(), Task.id)
    return list(session.scalars(stmt.limit(limit).offset(offset)))


def week_end(today: date) -> date:
    """The Sunday that closes the week of `today`."""
    return today + timedelta(days=6 - today.weekday())


_STATUS_RANK = case(
    (Task.status == "open", 0), (Task.status == "suggested", 1), (Task.status == "done", 2), else_=3
)
TASK_SORT = {
    "due_on": Task.due_on,
    "title": Task.title,
    "status": _STATUS_RANK,
    "created_at": Task.created_at,
}
DUE_FILTERS = ("overdue", "this_week", "later", "none")


def list_tasks_page(
    session: Session,
    ws_id: uuid.UUID,
    *,
    deal_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    status: str | None = None,
    due: str | None = None,
    owner_user_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    sort: str | None = None,
    direction: str | None = None,
    today: date | None = None,
    viewer: Viewer | None = None,
) -> tuple[list[Task], int]:
    """Visible tasks, paged. `due`: overdue (open or suggested, before today), this_week (today
    to Sunday), later (after Sunday) or none (no date). Default order: open first, earliest due."""
    today = today or date.today()
    cond = [
        Task.workspace_id == ws_id,
        *visibility.conds(visibility.account_or_deal(viewer, Task.account_id, Task.deal_id)),
    ]
    if deal_id is not None:
        cond.append(Task.deal_id == deal_id)
    if account_id is not None:
        cond.append(Task.account_id == account_id)
    if status:
        cond.append(Task.status == status)
    if owner_user_id is not None:
        cond.append(Task.owner_user_id == owner_user_id)
    if due == "overdue":
        cond += [Task.due_on < today, Task.status.in_(("open", "suggested"))]
    elif due == "this_week":
        cond += [Task.due_on >= today, Task.due_on <= week_end(today)]
    elif due == "later":
        cond.append(Task.due_on > week_end(today))
    elif due == "none":
        cond.append(Task.due_on.is_(None))
    elif due:
        raise InvalidInputError(f"due must be one of {', '.join(DUE_FILTERS)}")
    total = session.scalar(select(func.count()).select_from(Task).where(*cond)) or 0
    default = [_STATUS_RANK, Task.due_on.asc().nulls_last(), Task.created_at.desc()]
    order = order_clauses(TASK_SORT, sort, direction, default, Task.id)
    stmt = select(Task).where(*cond).order_by(*order)
    return list(session.scalars(stmt.limit(limit).offset(offset))), total


def create_suggested(
    session: Session,
    ws_id: uuid.UUID,
    *,
    title: str,
    evidence: dict[str, Any],
    deal_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
) -> Task:
    """An AI-suggested task: status `suggested`, source `ai_suggested`, the quoted sentence in
    `evidence`. It becomes `open` only through `accept_task` (a person)."""
    row = create_task(
        session, ws_id, title=title, deal_id=deal_id, account_id=account_id, source="ai_suggested"
    )
    row.status = "suggested"
    row.evidence = evidence
    session.flush()
    return row
