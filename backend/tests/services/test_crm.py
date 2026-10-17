"""CRM services against the real schema (rolled back after each test)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.models import Comment, Contact, Note
from app.domain.enums import DealStage
from app.domain.schemas import AccountIn, ContactIn, DealIn, UserIn
from app.services import (
    accounts,
    comments,
    contacts,
    deals,
    notes,
    users,
    workspaces,
)
from app.services.errors import AlreadyExistsError, InvalidInputError, NotFoundError

pytestmark = pytest.mark.integration


def mk_account(s: Session, ws: uuid.UUID, name: str = "Acme"):
    return accounts.create_account(s, ws, AccountIn(name=name))


def mk_contact(s: Session, ws: uuid.UUID, account_id, name="Jane", reports_to=None):
    return contacts.create_contact(
        s, ws, ContactIn(account_id=account_id, full_name=name, reports_to_id=reports_to)
    )


# --- workspaces / users / accounts ------------------------------------------------------------
def test_workspace_lifecycle(db_session: Session):
    ws = workspaces.create_workspace(db_session, "demo-planted", "Planted", is_demo=True)
    assert ws.is_demo and workspaces.get_workspace_by_slug(db_session, "demo-planted") == ws
    assert ws in workspaces.list_workspaces(db_session)
    with pytest.raises(AlreadyExistsError):
        workspaces.create_workspace(db_session, "demo-planted", "again")
    with pytest.raises(InvalidInputError):
        workspaces.create_workspace(db_session, "Bad Slug!", "x")
    with pytest.raises(NotFoundError):
        workspaces.delete_workspace(db_session, "nope")


def test_users_unique_email_and_scrubbing(db_session: Session, ws_id):
    u = users.create_user(db_session, ws_id, UserIn(display_name="Al\x00ice", email="a@x.io"))
    assert u.display_name == "Alice"
    with pytest.raises(AlreadyExistsError):
        users.create_user(db_session, ws_id, UserIn(display_name="B", email="a@x.io"))
    assert [x.id for x in users.list_users(db_session, ws_id)] == [u.id]


def test_cross_workspace_refusal(db_session: Session, ws_id):
    other = workspaces.create_workspace(db_session, "other", "Other").id
    acc = mk_account(db_session, ws_id)
    assert accounts.get_account(db_session, other, acc.id) is None
    with pytest.raises(NotFoundError):
        mk_contact(db_session, other, acc.id)
    foreign_user = users.create_user(db_session, other, UserIn(display_name="X"))
    with pytest.raises(NotFoundError):
        deals.create_deal(
            db_session,
            ws_id,
            DealIn(account_id=acc.id, owner_id=foreign_user.id, name="d", created_on=date.today()),
        )
    with pytest.raises(NotFoundError):
        accounts.erase_account(db_session, other, acc.id)
    assert accounts.list_accounts(db_session, other) == []


# --- contacts / org chart ---------------------------------------------------------------------
def test_org_chart_and_cycle_refusal(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id)
    ceo = mk_contact(db_session, ws_id, acc.id, "CEO")
    vp = mk_contact(db_session, ws_id, acc.id, "VP", reports_to=ceo.id)
    rep = mk_contact(db_session, ws_id, acc.id, "Rep", reports_to=vp.id)
    chart = dict((c.id, m) for c, m in contacts.org_chart(db_session, ws_id, acc.id))
    assert chart == {ceo.id: None, vp.id: ceo.id, rep.id: vp.id}
    with pytest.raises(InvalidInputError):
        contacts.set_reports_to(db_session, ws_id, ceo.id, rep.id)  # cycle
    with pytest.raises(InvalidInputError):
        contacts.set_reports_to(db_session, ws_id, ceo.id, ceo.id)  # self
    contacts.set_reports_to(db_session, ws_id, rep.id, None)
    assert contacts.get_contact(db_session, ws_id, rep.id).reports_to_id is None
    assert len(contacts.list_contacts(db_session, ws_id, acc.id)) == 3


def test_reports_to_must_be_same_account(db_session: Session, ws_id):
    a, b = mk_account(db_session, ws_id, "A"), mk_account(db_session, ws_id, "B")
    boss = mk_contact(db_session, ws_id, a.id, "Boss")
    with pytest.raises(InvalidInputError):
        mk_contact(db_session, ws_id, b.id, "Other", reports_to=boss.id)
    other = mk_contact(db_session, ws_id, b.id, "Other")
    with pytest.raises(InvalidInputError):
        contacts.set_reports_to(db_session, ws_id, other.id, boss.id)


# --- deals ------------------------------------------------------------------------------------
def test_deals(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id)
    d = deals.create_deal(
        db_session,
        ws_id,
        DealIn(
            account_id=acc.id,
            name="D",
            amount_eur=Decimal("1000"),
            stage=DealStage.CLOSED_WON,
            created_on=date(2026, 1, 1),
        ),
    )
    assert d.closed_on is None  # accepted: real data is like that
    with pytest.raises(InvalidInputError):
        deals.create_deal(
            db_session,
            ws_id,
            DealIn(
                account_id=acc.id,
                name="bad",
                created_on=date(2026, 2, 1),
                closed_on=date(2026, 1, 1),
            ),
        )
    deals.set_stage(db_session, ws_id, d.id, DealStage.CLOSED_LOST, date(2026, 3, 1))
    assert (d.stage, d.closed_on) == ("closed_lost", date(2026, 3, 1))
    deals.set_stage(db_session, ws_id, d.id, DealStage.NEGOTIATION)
    assert d.closed_on is None
    assert deals.list_deals(db_session, ws_id) == [d]


# --- notes: append-only -----------------------------------------------------------------------
def test_note_chain_correction_and_soft_delete(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id)
    c = mk_contact(db_session, ws_id, acc.id)
    u = users.create_user(db_session, ws_id, UserIn(display_name="U"))
    n1 = notes.add_note(db_session, ws_id, c.id, u.id, "first")
    n2 = notes.correct_note(db_session, ws_id, n1.id, u.id, "second")
    n3 = notes.correct_note(db_session, ws_id, n1.id, u.id, "third")  # attaches to the latest
    assert n3.corrects_id == n2.id
    other = notes.add_note(db_session, ws_id, c.id, u.id, "other")
    assert [n.body for n in notes.current_notes(db_session, ws_id, c.id)] == ["third", "other"]
    assert [n.body for n in notes.note_history(db_session, ws_id, n2.id)] == [
        "first",
        "second",
        "third",
    ]
    notes.delete_note(db_session, ws_id, n2.id, u.id)
    assert [n.id for n in notes.current_notes(db_session, ws_id, c.id)] == [other.id]
    with pytest.raises(InvalidInputError):
        notes.delete_note(db_session, ws_id, n1.id, u.id)
    with pytest.raises(InvalidInputError):
        notes.correct_note(db_session, ws_id, n1.id, u.id, "x")
    with pytest.raises(InvalidInputError):
        notes.add_note(db_session, ws_id, c.id, u.id, "  \x00 ")


def test_comments_mirror_notes(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id)
    c1 = comments.add_comment(db_session, ws_id, acc.id, None, "hello")
    c2 = comments.correct_comment(db_session, ws_id, c1.id, None, "hello!")
    assert [c.body for c in comments.current_comments(db_session, ws_id, acc.id)] == ["hello!"]
    assert [c.id for c in comments.comment_history(db_session, ws_id, c1.id)] == [c1.id, c2.id]
    comments.delete_comment(db_session, ws_id, c2.id, None)
    assert comments.current_comments(db_session, ws_id, acc.id) == []


def _raw(session: Session, sql: str, **params):
    """Run raw SQL in a savepoint so a refused statement does not poison the test transaction."""
    with session.begin_nested():
        session.execute(text(sql), params)


def test_trigger_refuses_updates_and_deletes(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id)
    c = mk_contact(db_session, ws_id, acc.id)
    n = notes.add_note(db_session, ws_id, c.id, None, "body")
    for sql in (
        "UPDATE note SET body = 'x' WHERE id = :id",
        "UPDATE note SET created_at = now() - interval '1 day' WHERE id = :id",
        "UPDATE note SET corrects_id = id WHERE id = :id",
        "DELETE FROM note WHERE id = :id",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            _raw(db_session, sql, id=n.id)
    other = mk_contact(db_session, ws_id, acc.id, "Other")
    with pytest.raises(DBAPIError, match="append-only"):
        _raw(db_session, "UPDATE note SET contact_id = :c WHERE id = :id", c=other.id, id=n.id)
    # the same rules hold for comments
    cm = comments.add_comment(db_session, ws_id, acc.id, None, "b")
    with pytest.raises(DBAPIError, match="append-only"):
        _raw(db_session, "UPDATE comment SET body = 'x' WHERE id = :id", id=cm.id)
    with pytest.raises(DBAPIError, match="append-only"):
        _raw(db_session, "DELETE FROM comment WHERE id = :id", id=cm.id)


def test_trigger_second_soft_delete_and_user_deletion(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id)
    c = mk_contact(db_session, ws_id, acc.id)
    u = users.create_user(db_session, ws_id, UserIn(display_name="U"))
    n = notes.add_note(db_session, ws_id, c.id, u.id, "body")
    notes.delete_note(db_session, ws_id, n.id, u.id)
    with pytest.raises(DBAPIError, match="append-only"):
        _raw(db_session, "UPDATE note SET deleted_at = now() WHERE id = :id", id=n.id)
    with pytest.raises(DBAPIError, match="append-only"):
        _raw(db_session, "UPDATE note SET deleted_at = NULL WHERE id = :id", id=n.id)
    # deleting the user nulls author_id and deleted_by_id (FK SET NULL) through the trigger
    db_session.execute(text("DELETE FROM app_user WHERE id = :id"), {"id": u.id})
    db_session.expire_all()
    row = db_session.get(Note, n.id)
    assert row.author_id is None and row.deleted_by_id is None and row.deleted_at is not None
    assert row.body == "body"


# --- erasure ----------------------------------------------------------------------------------
def test_erase_contact_deletes_notes_and_unlinks_reports(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id)
    boss = mk_contact(db_session, ws_id, acc.id, "Boss")
    rep = mk_contact(db_session, ws_id, acc.id, "Rep", reports_to=boss.id)
    n = notes.add_note(db_session, ws_id, boss.id, None, "secret")
    notes.correct_note(db_session, ws_id, n.id, None, "secret2")
    keep = notes.add_note(db_session, ws_id, rep.id, None, "keep")
    boss_id, rep_id, keep_id = boss.id, rep.id, keep.id
    contacts.erase_contact(db_session, ws_id, boss_id)
    assert db_session.get(Contact, boss_id) is None
    assert db_session.scalar(select(func.count()).select_from(Note)) == 1
    assert db_session.get(Note, keep_id) is not None
    assert db_session.get(Contact, rep_id).reports_to_id is None
    # the erasure switch is off again: plain deletes are refused
    with pytest.raises(DBAPIError, match="append-only"):
        _raw(db_session, "DELETE FROM note WHERE id = :id", id=keep_id)


def test_erase_account_and_delete_workspace_cascade(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id)
    c = mk_contact(db_session, ws_id, acc.id)
    notes.add_note(db_session, ws_id, c.id, None, "n")
    comments.add_comment(db_session, ws_id, acc.id, None, "c")
    deals.create_deal(
        db_session, ws_id, DealIn(account_id=acc.id, name="d", created_on=date(2026, 1, 1))
    )
    accounts.erase_account(db_session, ws_id, acc.id)
    for model in (Contact, Note, Comment):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0
    assert deals.list_deals(db_session, ws_id) == []

    acc2 = mk_account(db_session, ws_id, "B")
    mk_contact(db_session, ws_id, acc2.id)
    notes.add_note(db_session, ws_id, contacts.list_contacts(db_session, ws_id)[0].id, None, "n")
    workspaces.delete_workspace(db_session, "test-ws")
    assert workspaces.get_workspace_by_slug(db_session, "test-ws") is None
    assert db_session.scalar(select(func.count()).select_from(Note)) == 0


# --- SR4 hardening ----------------------------------------------------------------------------
def test_truncate_is_refused(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id)
    c = mk_contact(db_session, ws_id, acc.id)
    notes.add_note(db_session, ws_id, c.id, None, "body")
    comments.add_comment(db_session, ws_id, acc.id, None, "b")
    for sql in (
        "TRUNCATE note",
        "TRUNCATE comment",
        "TRUNCATE contact CASCADE",
        "TRUNCATE account CASCADE",
        "TRUNCATE workspace CASCADE",
    ):
        with pytest.raises(DBAPIError, match="TRUNCATE refused"):
            _raw(db_session, sql)


def test_second_correction_of_a_version_is_refused_by_the_index(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id)
    c = mk_contact(db_session, ws_id, acc.id)
    n1 = notes.add_note(db_session, ws_id, c.id, None, "first")
    notes.correct_note(db_session, ws_id, n1.id, None, "second")
    cm = comments.add_comment(db_session, ws_id, acc.id, None, "a")
    comments.correct_comment(db_session, ws_id, cm.id, None, "b")
    cases = (
        ("note", "contact_id", c.id, n1.id),
        ("comment", "account_id", acc.id, cm.id),
    )
    for table, parent_col, parent_id, target in cases:
        with pytest.raises(DBAPIError, match="uq_"):
            _raw(
                db_session,
                f"INSERT INTO {table} (id, workspace_id, {parent_col}, body, corrects_id) "  # noqa: S608
                "VALUES (gen_random_uuid(), :w, :p, 'x', :t)",
                w=ws_id,
                p=parent_id,
                t=target,
            )


def test_concurrent_correction_becomes_a_service_error(db_session: Session, ws_id, monkeypatch):
    acc = mk_account(db_session, ws_id)
    c = mk_contact(db_session, ws_id, acc.id)
    n1 = notes.add_note(db_session, ws_id, c.id, None, "first")
    # Simulate the race: another session already attached a correction to n1 that this
    # session's (stale) chain does not know about.
    from app.services import _appendonly

    real = _appendonly.history
    notes.correct_note(db_session, ws_id, n1.id, None, "winner")
    monkeypatch.setattr(
        _appendonly,
        "history",
        lambda *a, **k: [real(*a, **k)[0]],  # stale view: only n1
    )
    with pytest.raises(InvalidInputError, match="corrected concurrently"):
        notes.correct_note(db_session, ws_id, n1.id, None, "loser")


def test_author_cannot_be_nulled_by_direct_update(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id)
    c = mk_contact(db_session, ws_id, acc.id)
    u = users.create_user(db_session, ws_id, UserIn(display_name="U"))
    n = notes.add_note(db_session, ws_id, c.id, u.id, "body")
    with pytest.raises(DBAPIError, match="author_id is immutable"):
        _raw(db_session, "UPDATE note SET author_id = NULL WHERE id = :id", id=n.id)
    notes.delete_note(db_session, ws_id, n.id, u.id)
    with pytest.raises(DBAPIError, match="deleted_by_id is immutable"):
        _raw(db_session, "UPDATE note SET deleted_by_id = NULL WHERE id = :id", id=n.id)
    db_session.execute(text("DELETE FROM app_user WHERE id = :id"), {"id": u.id})
    db_session.expire_all()
    row = db_session.get(Note, n.id)
    assert row.author_id is None and row.deleted_by_id is None


def test_reports_to_takes_the_account_advisory_lock(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id)
    a = mk_contact(db_session, ws_id, acc.id, "A")
    b = mk_contact(db_session, ws_id, acc.id, "B", reports_to=a.id)
    contacts.set_reports_to(db_session, ws_id, a.id, None)
    held = db_session.execute(
        text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()")
    ).scalar_one()
    assert held >= 1 and b.reports_to_id == a.id
