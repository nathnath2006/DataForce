from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.connectors import store
from app.db.models import OAuthPending
from app.services import workspaces


def make_pending(db, ws, state, **kw):
    store.create_pending(
        db,
        ws.id,
        state=state,
        browser_secret="b-" + state,
        verifier_enc="v",
        issuer="https://api.tamtam.ai",
        resource="https://api.tamtam.ai/mcp",
        client_id="c",
        client_secret_enc=None,
        redirect_uri="http://127.0.0.1:8800/cb",
        **kw,
    )


def test_expired_pending_rows_are_purged_on_the_next_connect(db_session, ws):
    make_pending(db_session, ws, "old")
    db_session.scalars(select(OAuthPending)).one().expires_at = datetime.now(UTC) - timedelta(
        minutes=1
    )
    other = workspaces.create_workspace(db_session, "other-ws", "Other")
    make_pending(db_session, other, "new")
    assert [p.state_hash for p in db_session.scalars(select(OAuthPending))] == [
        store.sha256_hex("new")
    ]


def test_purge_counts_only_expired_rows(db_session, ws):
    make_pending(db_session, ws, "fresh")
    assert store.purge_expired_pending(db_session) == 0


def test_take_is_single_use_and_does_not_touch_other_flows(db_session, ws):
    other = workspaces.create_workspace(db_session, "other-ws", "Other")
    make_pending(db_session, ws, "a")
    make_pending(db_session, other, "b")
    taken = store.take_pending(db_session, "a")
    assert taken is not None and taken.workspace_id == ws.id
    assert store.take_pending(db_session, "a") is None
    assert store.take_pending(db_session, "b") is not None


def test_only_hashes_are_stored(db_session, ws):
    make_pending(db_session, ws, "plain-state")
    row = db_session.scalars(select(OAuthPending)).one()
    assert "plain-state" not in (row.state_hash, row.browser_hash)
    assert len(row.state_hash) == 64
