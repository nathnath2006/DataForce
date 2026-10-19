"""Sealed, workspace-scoped contact channels."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.db.models import ContactChannel
from app.domain.enums import ChannelKind
from app.enrichment.errors import EnrichmentConfigError
from app.services import channels, contacts, workspaces
from app.services.errors import InvalidInputError, NotFoundError
from tests.connectors.conftest import make_contact


def add(db, ws, contact, settings, value="jane@acme.example", kind=ChannelKind.EMAIL):
    return channels.add_channel(
        db,
        ws.id,
        contact.id,
        kind,
        value,
        provider="tamtam_mcp",
        credits_used=1,
        raw_tool="enrich_contact",
        settings=settings,
    )


def test_values_are_sealed_at_rest(db_session, settings, ws, contact):
    row = add(db_session, ws, contact, settings)
    raw = db_session.execute(
        text("select value_enc from contact_channel where id = :i"), {"i": row.id}
    ).scalar_one()
    assert "jane" not in raw and "acme" not in raw
    assert channels.channel_value(row, settings) == "jane@acme.example"
    assert float(row.credits_used) == 1.0 and row.raw_tool == "enrich_contact"


def test_adding_needs_the_secret_key(db_session, ws, contact):
    from app.config import Settings

    with pytest.raises(EnrichmentConfigError, match="secrets init"):
        add(db_session, ws, contact, Settings(_env_file=None, environment="test"))
    assert (
        db_session.scalars(select(ContactChannel).where(ContactChannel.workspace_id == ws.id)).all()
        == []
    )


def test_the_same_value_is_replaced_not_duplicated(db_session, settings, ws, contact):
    add(db_session, ws, contact, settings)
    add(db_session, ws, contact, settings)
    add(db_session, ws, contact, settings, "+33 6 39 98 00 00", ChannelKind.MOBILE)
    assert len(channels.list_channels(db_session, ws.id, contact.id)) == 2


@pytest.mark.parametrize("value", ["", "   ", "x" * 400])
def test_empty_or_oversized_values_are_refused(db_session, settings, ws, contact, value):
    with pytest.raises(InvalidInputError):
        add(db_session, ws, contact, settings, value)


def test_a_value_the_key_cannot_open_is_shown_as_unreadable_but_deletable(
    db_session, settings, ws, contact
):
    from cryptography.fernet import Fernet

    from app.config import Settings

    row = add(db_session, ws, contact, settings)
    other = Settings(
        _env_file=None, environment="test", dataforce_secret_key=Fernet.generate_key().decode()
    )
    assert channels.channel_value(row, other) == channels.UNREADABLE
    channels.delete_channel(db_session, ws.id, contact.id, row.id)
    assert channels.list_channels(db_session, ws.id, contact.id) == []


def test_delete_is_a_hard_delete(db_session, settings, ws, contact):
    row = add(db_session, ws, contact, settings)
    channels.delete_channel(db_session, ws.id, contact.id, row.id)
    count = db_session.execute(text("select count(*) from contact_channel")).scalar_one()
    assert count == 0


def test_isolation_between_workspaces_and_contacts(db_session, settings, ws, contact):
    row = add(db_session, ws, contact, settings)
    other_ws = workspaces.create_workspace(db_session, "other", "Other")
    other_contact = make_contact(db_session, other_ws, "John Roe")
    # the row of one workspace is invisible and undeletable from another
    with pytest.raises(NotFoundError):
        channels.delete_channel(db_session, other_ws.id, other_contact.id, row.id)
    with pytest.raises(NotFoundError):
        channels.list_channels(db_session, other_ws.id, contact.id)
    with pytest.raises(NotFoundError):
        add(db_session, other_ws, contact, settings)
    # ... and a channel of another contact of the same workspace is not reachable by id either
    sibling = make_contact(db_session, ws, "Sam Lee")
    with pytest.raises(NotFoundError):
        channels.delete_channel(db_session, ws.id, sibling.id, row.id)
    assert len(channels.list_channels(db_session, ws.id, contact.id)) == 1


def test_delete_all_for_contact(db_session, settings, ws, contact):
    add(db_session, ws, contact, settings)
    add(db_session, ws, contact, settings, "+33 6 39 98 00 00", ChannelKind.MOBILE)
    sibling = make_contact(db_session, ws, "Sam Lee")
    keep = add(db_session, ws, sibling, settings, "sam@acme.example")
    assert channels.delete_channels_for_contact(db_session, ws.id, contact.id) == 2
    assert [r.id for r in channels.list_channels(db_session, ws.id, sibling.id)] == [keep.id]


def test_erasing_a_contact_cascades_to_its_channels(db_session, settings, ws, contact):
    add(db_session, ws, contact, settings)
    sibling = make_contact(db_session, ws, "Sam Lee")
    add(db_session, ws, sibling, settings, "sam@acme.example")
    contacts.erase_contact(db_session, ws.id, contact.id)
    remaining = db_session.scalars(
        select(ContactChannel).where(ContactChannel.workspace_id == ws.id)
    ).all()
    assert [r.contact_id for r in remaining] == [sibling.id]
