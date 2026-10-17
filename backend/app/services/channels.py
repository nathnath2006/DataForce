"""Enriched contact channels (email / mobile): sealed at rest, workspace-scoped, hard-deleted.

Values only come from an explicit lookup click. They are never logged or put in an error message.
Erasing a contact removes its channels through the foreign key (ON DELETE CASCADE).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors.crypto import UnsealError, seal, unseal
from app.db.models import ContactChannel
from app.domain.enums import ChannelKind
from app.services._common import get_scoped, require_contact
from app.services.errors import InvalidInputError, NotFoundError
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
