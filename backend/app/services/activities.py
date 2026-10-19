"""Activities: calls, emails and meetings logged on an account, optionally on a deal (M4)."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Activity, ActivityParticipant, Contact
from app.services._common import get_scoped, require, require_account, require_deal, require_user
from app.services.errors import InvalidInputError
from app.services.textclean import scrub_optional, scrub_text

KINDS = ("call", "email", "meeting", "other")
DIRECTIONS = ("inbound", "outbound")
SUBJECT_MAX = 300
BODY_MAX = 10_000
_UPDATABLE = {"kind", "direction", "occurred_at", "subject", "body", "deal_id", "participant_ids"}


def _check_when(when: datetime) -> datetime:
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    if when > datetime.now(UTC):
        raise InvalidInputError("occurred_at cannot be in the future")
    return when


def _check_text(subject: str, body: str | None) -> tuple[str, str | None]:
    subject = scrub_text(subject).strip()
    if not subject:
        raise InvalidInputError("subject cannot be empty")
    if len(subject) > SUBJECT_MAX:
        raise InvalidInputError(f"subject is longer than {SUBJECT_MAX} characters")
    body = scrub_optional(body)
    if body is not None:
        body = body.strip() or None
    if body is not None and len(body) > BODY_MAX:
        raise InvalidInputError(f"body is longer than {BODY_MAX} characters")
    return subject, body


def _check_kind(kind: str, direction: str | None) -> None:
    if kind not in KINDS:
        raise InvalidInputError(f"kind must be one of {', '.join(KINDS)}")
    if direction is not None and direction not in DIRECTIONS:
        raise InvalidInputError("direction must be inbound or outbound")


def _check_participants(
    session: Session, ws_id: uuid.UUID, account_id: uuid.UUID, ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    unique = list(dict.fromkeys(ids))
    if not unique:
        return []
    ok = set(
        session.scalars(
            select(Contact.id).where(
                Contact.workspace_id == ws_id,
                Contact.account_id == account_id,
                Contact.id.in_(unique),
            )
        )
    )
    if ok != set(unique):
        raise InvalidInputError("participants must be contacts of this account")
    return unique


def _check_deal(
    session: Session, ws_id: uuid.UUID, account_id: uuid.UUID, deal_id: uuid.UUID | None
) -> None:
    if deal_id is None:
        return
    if require_deal(session, ws_id, deal_id).account_id != account_id:
        raise InvalidInputError("the deal belongs to another account")


def create_activity(
    session: Session,
    ws_id: uuid.UUID,
    account_id: uuid.UUID,
    *,
    kind: str,
    occurred_at: datetime,
    subject: str,
    direction: str | None = None,
    body: str | None = None,
    deal_id: uuid.UUID | None = None,
    participant_ids: list[uuid.UUID] | None = None,
    author_user_id: uuid.UUID | None = None,
    source: str = "manual",
    external_ref: str | None = None,
    check_future: bool = True,
) -> Activity:
    require_account(session, ws_id, account_id)
    _check_kind(kind, direction)
    _check_deal(session, ws_id, account_id, deal_id)
    if author_user_id is not None:
        require_user(session, ws_id, author_user_id)
    subject, body = _check_text(subject, body)
    when = _check_when(occurred_at) if check_future else occurred_at
    people = _check_participants(session, ws_id, account_id, participant_ids or [])
    row = Activity(
        workspace_id=ws_id,
        account_id=account_id,
        deal_id=deal_id,
        kind=kind,
        direction=direction,
        occurred_at=when,
        subject=subject,
        body=body,
        author_user_id=author_user_id,
        source=source,
        external_ref=external_ref,
    )
    session.add(row)
    session.flush()
    session.add_all(ActivityParticipant(activity_id=row.id, contact_id=c) for c in people)
    session.flush()
    return row


def require_activity(session: Session, ws_id: uuid.UUID, activity_id: uuid.UUID) -> Activity:
    return require(session, Activity, ws_id, activity_id)


def get_activity(session: Session, ws_id: uuid.UUID, activity_id: uuid.UUID) -> Activity | None:
    return get_scoped(session, Activity, ws_id, activity_id)


def update_activity(
    session: Session, ws_id: uuid.UUID, activity_id: uuid.UUID, changes: dict[str, Any]
) -> Activity:
    row = require_activity(session, ws_id, activity_id)
    unknown = set(changes) - _UPDATABLE
    if unknown:
        raise InvalidInputError(f"cannot update: {', '.join(sorted(unknown))}")
    kind = changes.get("kind", row.kind)
    direction = changes["direction"] if "direction" in changes else row.direction
    _check_kind(kind, direction)
    if "deal_id" in changes:
        _check_deal(session, ws_id, row.account_id, changes["deal_id"])
        row.deal_id = changes["deal_id"]
    if "subject" in changes or "body" in changes:
        if changes.get("subject", row.subject) is None:
            raise InvalidInputError("subject cannot be empty")
        subject, body = _check_text(
            changes.get("subject", row.subject), changes["body"] if "body" in changes else row.body
        )
        row.subject, row.body = subject, body
    if "occurred_at" in changes:
        if changes["occurred_at"] is None:
            raise InvalidInputError("occurred_at cannot be cleared")
        row.occurred_at = _check_when(changes["occurred_at"])
    row.kind, row.direction = kind, direction
    if changes.get("participant_ids") is not None:
        people = _check_participants(session, ws_id, row.account_id, changes["participant_ids"])
        old = {p.contact_id: p for p in participant_rows(session, [row.id])}
        for cid, p in old.items():
            if cid not in people:
                session.delete(p)
        session.add_all(
            ActivityParticipant(activity_id=row.id, contact_id=c) for c in people if c not in old
        )
    session.flush()
    return row


def delete_activity(session: Session, ws_id: uuid.UUID, activity_id: uuid.UUID) -> None:
    session.delete(require_activity(session, ws_id, activity_id))
    session.flush()


def participant_rows(session: Session, activity_ids: list[uuid.UUID]) -> list[ActivityParticipant]:
    if not activity_ids:
        return []
    return list(
        session.scalars(
            select(ActivityParticipant).where(ActivityParticipant.activity_id.in_(activity_ids))
        )
    )


def participants_of(
    session: Session, ws_id: uuid.UUID, activity_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[uuid.UUID, str]]]:
    """{activity id: [(contact id, name)]} in one query, names sorted."""
    out: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = {}
    if not activity_ids:
        return out
    rows = session.execute(
        select(ActivityParticipant.activity_id, Contact.id, Contact.full_name)
        .join(Contact, Contact.id == ActivityParticipant.contact_id)
        .where(Contact.workspace_id == ws_id, ActivityParticipant.activity_id.in_(activity_ids))
        .order_by(Contact.full_name, Contact.id)
    )
    for aid, cid, name in rows:
        out.setdefault(aid, []).append((cid, name))
    return out


def list_activities(
    session: Session,
    ws_id: uuid.UUID,
    *,
    account_id: uuid.UUID | None = None,
    deal_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Activity]:
    """Newest first."""
    stmt = select(Activity).where(Activity.workspace_id == ws_id)
    if account_id is not None:
        require_account(session, ws_id, account_id)
        stmt = stmt.where(Activity.account_id == account_id)
    if deal_id is not None:
        require_deal(session, ws_id, deal_id)
        stmt = stmt.where(Activity.deal_id == deal_id)
    stmt = stmt.order_by(Activity.occurred_at.desc(), Activity.id.desc())
    return list(session.scalars(stmt.limit(limit).offset(offset)))


def _channel_patterns(session: Session, ws_id: uuid.UUID, contact: Contact) -> list[re.Pattern]:
    """Patterns for the contact's enriched emails and phones. The sealed values are opened in
    process only to build these; nothing is logged. A value that cannot be opened is skipped."""
    from app.connectors.crypto import unseal
    from app.db.models import ContactChannel
    from app.enrichment.errors import EnrichmentError

    out: list[re.Pattern] = []
    for ch in session.scalars(
        select(ContactChannel).where(
            ContactChannel.workspace_id == ws_id, ContactChannel.contact_id == contact.id
        )
    ):
        try:
            value = unseal(ch.value_enc).strip()
        except EnrichmentError:
            continue
        digits = re.sub(r"\D", "", value)
        if "@" in value:
            out.append(re.compile(re.escape(value), re.IGNORECASE))
        elif len(digits) >= 6:
            # the national number (last 9 digits), with any country code or trunk 0 before it
            sep = r"[\s.\-()]*"
            out.append(re.compile(r"(?:\+\d{1,3}|00\d{1,3}|0)?" + sep + sep.join(digits[-9:])))
    return out


def _mask_json(value: Any, mask: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, list):
        return [_mask_json(v, mask) for v in value]
    if isinstance(value, dict):
        return {k: _mask_json(v, mask) for k, v in value.items()}
    return value


def redact_contact(session: Session, ws_id: uuid.UUID, contact: Contact) -> int:
    """GDPR: an erased contact's name, email addresses and phone numbers are masked in the
    subjects and bodies of the account's activities, in its tasks' titles and in every string of
    its tasks' evidence (the participant links go with the contact, by cascade). Returns the
    number of rows changed. Runs in the caller's transaction."""
    from app.db.models import Task
    from app.services import documents

    rx = documents.name_pattern(contact.full_name)
    channels = _channel_patterns(session, ws_id, contact)
    if rx is None and not channels:
        return 0

    def mask(text: str) -> str:
        if rx is not None:
            text = documents._mask_name(rx, text)
        for c in channels:
            text = c.sub(lambda m: documents._placeholder(documents.ERASED, len(m.group(0))), text)
        return text

    n = 0
    for a in session.scalars(
        select(Activity).where(
            Activity.workspace_id == ws_id, Activity.account_id == contact.account_id
        )
    ):
        subject = mask(a.subject)
        body = mask(a.body) if a.body else a.body
        if subject != a.subject or body != a.body:
            a.subject, a.body = subject, body
            n += 1
    for t in session.scalars(
        select(Task).where(Task.workspace_id == ws_id, Task.account_id == contact.account_id)
    ):
        title = mask(t.title)
        evidence = _mask_json(t.evidence, mask)
        if title != t.title or evidence != t.evidence:
            t.title, t.evidence = title, evidence
            n += 1
    session.flush()
    return n
