"""Imported history keeps its original date (demo notes, later CRM imports), within limits."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.schemas import AccountIn, ContactIn
from app.services import accounts, contacts, notes
from app.services.errors import InvalidInputError

pytestmark = pytest.mark.integration


def _contact(db_session, ws_id):
    acc = accounts.create_account(db_session, ws_id, AccountIn(name="Acme"))
    return contacts.create_contact(db_session, ws_id, ContactIn(account_id=acc.id, full_name="A B"))


def test_original_dates_are_kept_and_checked(db_session, ws_id):
    c = _contact(db_session, ws_id)
    past = datetime(2026, 3, 1, 9, tzinfo=UTC)
    n = notes.add_note(db_session, ws_id, c.id, None, "met at a fair", created_at=past)
    assert n.created_at == past
    fixed = notes.correct_note(
        db_session, ws_id, n.id, None, "met at a trade fair", created_at=past + timedelta(days=2)
    )
    assert fixed.created_at == past + timedelta(days=2)
    with pytest.raises(InvalidInputError, match="older"):
        notes.correct_note(db_session, ws_id, n.id, None, "x", created_at=past)
    with pytest.raises(InvalidInputError, match="future"):
        notes.add_note(
            db_session, ws_id, c.id, None, "x", created_at=datetime.now(UTC) + timedelta(days=1)
        )
    with pytest.raises(InvalidInputError, match="timezone"):
        notes.add_note(db_session, ws_id, c.id, None, "x", created_at=datetime(2026, 1, 1))
