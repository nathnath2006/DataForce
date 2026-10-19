"""Synthetic stage histories, activities and tasks for an EXISTING demo workspace (M4).

Everything is invented. It is idempotent: a deal that already has stage events is skipped, so
running it twice changes nothing. Histories are consistent with the deal as it is: they end at
its current stage, and closing happens on `closed_on`."""

from __future__ import annotations

import random
import zlib
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Contact, Deal, DealStageEvent, Workspace
from app.domain.enums import DealStage
from app.services import activities, tasks
from app.services.errors import InvalidInputError

OPEN_PATH = ["prospecting", "qualification", "proposal", "negotiation"]

_SUBJECTS = {
    "call": ["Discovery call", "Follow-up call", "Pricing call", "Check-in call", "Technical call"],
    "email": [
        "Intro email",
        "Proposal sent",
        "Follow-up email",
        "Contract draft",
        "Questions answered",
    ],
    "meeting": [
        "Kick-off meeting",
        "Demo",
        "Steering committee",
        "On-site visit",
        "Review meeting",
    ],
}
_BODIES = [
    "Synthetic entry. Agreed next steps and a date for the next exchange.",
    "Synthetic entry. Open questions about scope and budget.",
    "Synthetic entry. Positive tone, waiting for internal approval.",
    None,
    None,
]
_TASKS = [
    "Send the proposal",
    "Schedule a demo",
    "Follow up by phone",
    "Prepare the contract",
    "Share references",
]


def _noon(d: date) -> datetime:
    return datetime.combine(d, time(12, 0), tzinfo=UTC)


def _stage_path(deal: Deal, rng: random.Random) -> list[str]:
    if deal.stage in OPEN_PATH:
        return OPEN_PATH[: OPEN_PATH.index(deal.stage) + 1]
    if deal.stage == DealStage.CLOSED_WON.value:
        return [*OPEN_PATH, deal.stage]
    reached = rng.randint(1, len(OPEN_PATH))  # lost somewhere along the way
    return [*OPEN_PATH[:reached], deal.stage]


def _dates(n: int, start: date, end: date, rng: random.Random, closed: bool) -> list[date]:
    """n non-decreasing dates in [start, end]; the first is `start`, the last `end` when closed."""
    span = max((end - start).days, 0)
    cuts = sorted(rng.randint(0, span) for _ in range(max(n - 1, 0)))
    days = [0, *cuts]
    if closed and n > 1:
        days[-1] = span
    return [start + timedelta(days=x) for x in days]


def _moment(d: date, i: int, n: int, today: date, now: datetime) -> datetime:
    if d == today:
        return now - timedelta(minutes=n - i)
    return _noon(d) + timedelta(minutes=i)


def backfill_workspace(
    session: Session, workspace_slug: str, *, today: date | None = None
) -> dict[str, Any]:
    ws = session.scalar(select(Workspace).where(Workspace.slug == workspace_slug))
    if ws is None:
        raise InvalidInputError(f"workspace {workspace_slug!r} not found")
    if not ws.is_demo:
        raise InvalidInputError(f"workspace {workspace_slug!r} is not a demo workspace")
    now = datetime.now(UTC)
    today = today or now.date()
    seeded = set(
        session.scalars(select(DealStageEvent.deal_id).where(DealStageEvent.workspace_id == ws.id))
    )
    people: dict[Any, list[Contact]] = {}
    for c in session.scalars(
        select(Contact).where(Contact.workspace_id == ws.id).order_by(Contact.id)
    ):
        people.setdefault(c.account_id, []).append(c)
    counts = {"deals": 0, "skipped": 0, "stage_events": 0, "activities": 0, "tasks": 0}
    for deal in session.scalars(
        select(Deal).where(Deal.workspace_id == ws.id).order_by(Deal.created_on, Deal.id)
    ):
        if deal.id in seeded:
            counts["skipped"] += 1
            continue
        rng = random.Random(zlib.crc32(f"{workspace_slug}:{deal.id}".encode()))  # noqa: S311 - synthetic data
        closed = deal.stage in (DealStage.CLOSED_WON.value, DealStage.CLOSED_LOST.value)
        start = min(deal.created_on, today)
        end = min(deal.closed_on or today, today) if closed else today
        end = max(end, start)
        path = _stage_path(deal, rng)
        days = _dates(len(path), start, end, rng, closed)
        for i, (stage, d) in enumerate(zip(path, days, strict=True)):
            session.add(
                DealStageEvent(
                    workspace_id=ws.id,
                    deal_id=deal.id,
                    from_stage=path[i - 1] if i else None,
                    to_stage=stage,
                    changed_at=_moment(d, i, len(path), today, now),
                    changed_by_id=deal.owner_id if i else None,
                    source="demo",
                )
            )
        counts["stage_events"] += len(path)
        contacts = people.get(deal.account_id, [])
        for _ in range(rng.randint(2, 6)):
            kind = rng.choices(["call", "email", "meeting"], weights=[4, 5, 2])[0]
            day = start + timedelta(days=rng.randint(0, max((end - start).days, 0)))
            at = _noon(day) + timedelta(hours=rng.randint(-3, 5))
            if at > now:
                at = now - timedelta(hours=1)
            who = rng.sample(contacts, k=min(len(contacts), rng.randint(0, 2))) if contacts else []
            activities.create_activity(
                session,
                ws.id,
                deal.account_id,
                kind=kind,
                direction=None if kind == "meeting" else rng.choice(["inbound", "outbound"]),
                occurred_at=at,
                subject=rng.choice(_SUBJECTS[kind]),
                body=rng.choice(_BODIES),
                deal_id=deal.id,
                participant_ids=[c.id for c in who],
                author_user_id=deal.owner_id,
                source="demo",
            )
            counts["activities"] += 1
        if not closed and rng.random() < 0.35:
            for _ in range(rng.randint(1, 2)):
                t = tasks.create_task(
                    session,
                    ws.id,
                    title=rng.choice(_TASKS),
                    deal_id=deal.id,
                    due_on=today + timedelta(days=rng.randint(-5, 14)),
                    owner_user_id=deal.owner_id,
                    source="demo",
                )
                if rng.random() < 0.3:
                    t.status = "done"
                    t.done_at = now - timedelta(days=rng.randint(0, 3))
                counts["tasks"] += 1
        counts["deals"] += 1
    session.flush()
    return counts
