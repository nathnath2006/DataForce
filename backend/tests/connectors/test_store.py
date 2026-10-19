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
    db_session.scalars(
        select(OAuthPending).where(OAuthPending.workspace_id == ws.id)
    ).one().expires_at = datetime.now(UTC) - timedelta(minutes=1)
    other = workspaces.create_workspace(db_session, "other-ws", "Other")
    make_pending(db_session, other, "new")
    assert [
        p.state_hash
        for p in db_session.scalars(
            select(OAuthPending).where(OAuthPending.workspace_id.in_([ws.id, other.id]))
        )
    ] == [store.sha256_hex("new")]


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
    row = db_session.scalars(select(OAuthPending).where(OAuthPending.workspace_id == ws.id)).one()
    assert "plain-state" not in (row.state_hash, row.browser_hash)
    assert len(row.state_hash) == 64


def test_take_pending_is_one_delete_returning_statement(db_session, ws):
    from sqlalchemy import event

    make_pending(db_session, ws, "a")
    seen: list[str] = []
    engine = db_session.get_bind().engine

    def spy(conn, cursor, statement, *args):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", spy)
    try:
        taken = store.take_pending(db_session, "a")
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    assert taken is not None and taken.browser_hash == store.sha256_hex("b-a")
    sql = [s for s in seen if "oauth_pending" in s.lower()]
    assert len(sql) == 1 and sql[0].lower().startswith("delete") and "returning" in sql[0].lower()


def test_connector_lock_is_a_transaction_level_advisory_lock(db_session, ws):
    from sqlalchemy import text

    count = "select count(*) from pg_locks where locktype='advisory' and pid=pg_backend_pid()"
    before = db_session.scalar(text(count))
    store.lock_connector(db_session, ws.id)
    assert db_session.scalar(text(count)) == before + 1


def test_update_tokens_is_conditional_on_the_credential_it_started_from(db_session, ws):
    store.save_credential(
        db_session,
        ws.id,
        status="connected",
        issuer="i",
        resource="r",
        client_id="c",
        redirect_uri="u",
        access_token_enc="old",
        refresh_token_enc=None,
    )
    cred = store.get_credential(db_session, ws.id)
    stamp = cred.connected_at
    kw = {"access_token_enc": "new", "refresh_token_enc": None, "token_expires_at": None}
    assert not store.update_tokens(
        db_session, ws.id, **kw, expected_connected_at=stamp, expected_access_token_enc="other"
    )
    assert store.update_tokens(
        db_session, ws.id, **kw, expected_connected_at=stamp, expected_access_token_enc="old"
    )
    assert cred.access_token_enc == "new"
