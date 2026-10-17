"""Enriched contact channels (email / mobile): sealed at rest, workspace-scoped, hard-deleted.

Values only come from an explicit lookup click. They are never logged or put in an error message.
Erasing a contact removes its channels through the foreign key (ON DELETE CASCADE).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.connectors.crypto import UnsealError, seal, unseal
from app.db.models import ContactChannel
from app.domain.enums import ChannelKind
from app.services._common import get_scoped, require_contact
from app.services.errors import AlreadyExistsError, InvalidInputError, NotFoundError
from app.services.textclean import scrub_text

MAX_VALUE_CHARS = 320
UNREADABLE = "[unreadable: secret key changed]"


def channel_value(row: ContactChannel, settings: Settings) -> str:
    """The unsealed value, for display. A value the current key cannot open shows a marker so the
    user can still delete the row."""
    try:
        return unseal(row.value_enc, settings)
    except UnsealError:
        return UNREADABLE


def list_channels(
    session: Session, ws_id: uuid.UUID, contact_id: uuid.UUID
) -> list[ContactChannel]:
    require_contact(session, ws_id, contact_id)
    return list(
        session.scalars(
            select(ContactChannel)
            .where(ContactChannel.workspace_id == ws_id, ContactChannel.contact_id == contact_id)
            .order_by(ContactChannel.fetched_at.desc(), ContactChannel.id)
        )
    )


def add_channel(
    session: Session,
    ws_id: uuid.UUID,
    contact_id: uuid.UUID,
    kind: ChannelKind,
    value: str,
    *,
    provider: str,
    credits_used: float | Decimal,
    raw_tool: str | None,
    settings: Settings,
) -> ContactChannel:
    """Store `value` sealed. The same value of the same kind is replaced, not duplicated."""
    require_contact(session, ws_id, contact_id)
    clean = scrub_text(value).strip()
    if not clean or len(clean) > MAX_VALUE_CHARS:
        raise InvalidInputError("the channel value is empty or too long")
    for old in list_channels(session, ws_id, contact_id):
        if old.kind == kind.value and channel_value(old, settings) == clean:
            session.delete(old)
    session.flush()
    row = ContactChannel(
        workspace_id=ws_id,
        contact_id=contact_id,
        kind=kind.value,
        value_enc=seal(clean, settings),
        provider=provider,
        credits_used=Decimal(str(credits_used)),
        raw_tool=scrub_text(raw_tool)[:200] if raw_tool else None,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def delete_channel(
    session: Session, ws_id: uuid.UUID, contact_id: uuid.UUID, channel_id: uuid.UUID
) -> None:
    row = get_scoped(session, ContactChannel, ws_id, channel_id)
    if row is None or row.contact_id != contact_id:
        raise NotFoundError("channel not found")
    session.delete(row)
    session.flush()


def delete_channels_for_contact(session: Session, ws_id: uuid.UUID, contact_id: uuid.UUID) -> int:
    require_contact(session, ws_id, contact_id)
    result = session.execute(
        delete(ContactChannel).where(
            ContactChannel.workspace_id == ws_id, ContactChannel.contact_id == contact_id
        )
    )
    session.expire_all()
    return result.rowcount or 0


_LOOKUP_LOCK_NS = 7_461_220_008
LOOKUP_RUNNING = "a lookup for this contact is already running"


@asynccontextmanager
async def lookup_guard(
    session: Session, ws_id: uuid.UUID, contact_id: uuid.UUID
) -> AsyncIterator[None]:
    """In-flight guard for paid lookups of one (workspace, contact). A session-level
    `pg_try_advisory_lock` on its own connection (the request's session gives its connection
    back while the network call runs), released in `finally`. A second request meanwhile gets
    a 409 `conflict` and sends nothing."""
    engine = session.get_bind().engine
    key = func.hashtextextended(f"{ws_id}:{contact_id}", _LOOKUP_LOCK_NS)

    def acquire():
        conn = engine.connect()
        try:
            got = conn.execute(select(func.pg_try_advisory_lock(key))).scalar_one()
            conn.commit()
        except BaseException:
            conn.close()
            raise
        if not got:
            conn.close()
            return None
        return conn

    def release(conn) -> None:
        try:
            conn.execute(select(func.pg_advisory_unlock(key)))
            conn.commit()
        finally:
            conn.close()  # closing the connection drops a session lock anyway

    conn = await run_in_threadpool(acquire)
    if conn is None:
        raise AlreadyExistsError(LOOKUP_RUNNING)
    try:
        yield
    finally:
        await run_in_threadpool(release, conn)


def refuse_stored_kinds(
    session: Session, ws_id: uuid.UUID, contact_id: uuid.UUID, kinds: list[str]
) -> None:
    """A paid lookup for a kind the contact already has is refused (no traffic): delete the
    stored value first if a fresh one is wanted."""
    stored = {row.kind for row in list_channels(session, ws_id, contact_id)}
    dupes = [k for k in dict.fromkeys(kinds) if k in stored]
    if dupes:
        raise AlreadyExistsError(
            f"this contact already has a stored {' and '.join(dupes)}; delete the stored value "
            "first if you want to look it up again"
        )
