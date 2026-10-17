"""Partial updates, paged lists with search, and aggregate counts (services added for the UI)."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.domain.enums import DealStage, Segment
from app.domain.schemas import AccountIn, ContactIn, DealIn, UserIn
from app.services import accounts, contacts, deals, notes, users, workspaces
from app.services.errors import InvalidInputError, NotFoundError

pytestmark = pytest.mark.integration


def mk_account(s: Session, ws, name="Acme", **kw):
    return accounts.create_account(s, ws, AccountIn(name=name, **kw))


def mk_deal(s: Session, ws, acc, name="D", **kw):
    return deals.create_deal(
        s,
        ws,
        DealIn(
            account_id=acc.id, name=name, created_on=kw.pop("created_on", date(2026, 1, 1)), **kw
        ),
    )


def test_update_account_partial(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id, domain="a.io", region="EU", segment=Segment.SMB)
    accounts.update_account(db_session, ws_id, acc.id, {"industry": "SaaS", "region": None})
    assert (acc.name, acc.domain, acc.industry, acc.region) == ("Acme", "a.io", "SaaS", None)
    accounts.update_account(
        db_session, ws_id, acc.id, {"country": "fr", "segment": Segment.ENTERPRISE}
    )
    assert (acc.country, acc.segment) == ("FR", "enterprise")
    with pytest.raises(InvalidInputError):
        accounts.update_account(db_session, ws_id, acc.id, {"name": None})
    with pytest.raises(InvalidInputError):
        accounts.update_account(db_session, ws_id, acc.id, {"source": "x"})
    other = workspaces.create_workspace(db_session, "other", "Other").id
    with pytest.raises(NotFoundError):
        accounts.update_account(db_session, other, acc.id, {"industry": "x"})


def test_update_contact(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id)
    c = contacts.create_contact(
        db_session, ws_id, ContactIn(account_id=acc.id, full_name="Jo", title="CTO")
    )
    contacts.update_contact(db_session, ws_id, c.id, {"title": None})
    assert (c.full_name, c.title) == ("Jo", None)
    with pytest.raises(InvalidInputError):
        contacts.update_contact(db_session, ws_id, c.id, {"full_name": " "})
    with pytest.raises(InvalidInputError):
        contacts.update_contact(db_session, ws_id, c.id, {"reports_to_id": None})


def test_update_and_delete_deal(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id)
    other = workspaces.create_workspace(db_session, "other", "Other").id
    foreign = users.create_user(db_session, other, UserIn(display_name="X"))
    mine = users.create_user(db_session, ws_id, UserIn(display_name="Me"))
    d = mk_deal(db_session, ws_id, acc)
    deals.set_stage(db_session, ws_id, d.id, DealStage.CLOSED_WON, date(2026, 2, 1))
    deals.update_deal(db_session, ws_id, d.id, {"owner_id": mine.id, "name": "Renamed"})
    assert (d.owner_id, d.name) == (mine.id, "Renamed")
    with pytest.raises(NotFoundError):
        deals.update_deal(db_session, ws_id, d.id, {"owner_id": foreign.id})
    with pytest.raises(InvalidInputError):  # created after closed_on
        deals.update_deal(db_session, ws_id, d.id, {"created_on": date(2026, 3, 1)})
    deals.update_deal(db_session, ws_id, d.id, {"owner_id": None})
    assert d.owner_id is None
    deals.delete_deal(db_session, ws_id, d.id)
    assert deals.get_deal(db_session, ws_id, d.id) is None
    with pytest.raises(NotFoundError):
        deals.delete_deal(db_session, ws_id, d.id)


def test_account_pages_search_and_counts(db_session: Session, ws_id):
    a = mk_account(db_session, ws_id, "Alpha 100%", domain="alpha.io", segment=Segment.SMB)
    b = mk_account(db_session, ws_id, "Beta_co", segment=Segment.ENTERPRISE)
    mk_account(db_session, ws_id, "Gamma")
    c = contacts.create_contact(db_session, ws_id, ContactIn(account_id=a.id, full_name="Jo"))
    contacts.create_contact(
        db_session, ws_id, ContactIn(account_id=a.id, full_name="Al", reports_to_id=c.id)
    )
    d1 = mk_deal(db_session, ws_id, a, "open")
    d2 = mk_deal(db_session, ws_id, a, "won")
    deals.set_stage(db_session, ws_id, d2.id, DealStage.CLOSED_WON, date(2026, 2, 1))
    rows, total = accounts.list_accounts_page(db_session, ws_id, limit=2)
    assert (len(rows), total) == (2, 3)
    assert [
        r.name for r in accounts.list_accounts_page(db_session, ws_id, limit=2, offset=2)[0]
    ] == ["Gamma"]
    assert accounts.list_accounts_page(db_session, ws_id, q="%")[1] == 1  # literal percent
    assert [r.name for r in accounts.list_accounts_page(db_session, ws_id, q="_")[0]] == ["Beta_co"]
    assert accounts.list_accounts_page(db_session, ws_id, q="ALPHA.io")[1] == 1
    assert accounts.list_accounts_page(db_session, ws_id, segment="enterprise")[0] == [b]
    counts = accounts.account_counts(db_session, ws_id, [a.id, b.id])
    assert counts == {a.id: (2, 2, 1), b.id: (0, 0, 0)}
    assert d1.id != d2.id


def test_contact_extras_and_filters(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id)
    boss = contacts.create_contact(
        db_session, ws_id, ContactIn(account_id=acc.id, full_name="Boss")
    )
    rep = contacts.create_contact(
        db_session, ws_id, ContactIn(account_id=acc.id, full_name="Rep", reports_to_id=boss.id)
    )
    n1 = notes.add_note(db_session, ws_id, boss.id, None, "one")
    notes.correct_note(db_session, ws_id, n1.id, None, "one fixed")
    n2 = notes.add_note(db_session, ws_id, boss.id, None, "two")
    notes.delete_note(db_session, ws_id, n2.id, None)
    extras = contacts.contact_extras(db_session, ws_id, [boss.id, rep.id])
    assert extras[boss.id]["n_notes"] == 1 and extras[boss.id]["n_direct_reports"] == 1
    assert extras[rep.id]["reports_to_name"] == "Boss" and extras[rep.id]["account_name"] == "Acme"
    assert extras[rep.id]["n_channels"] == 0
    assert contacts.list_contacts_page(db_session, ws_id, q="re")[1] == 1
    assert contacts.list_contacts_page(db_session, ws_id, account_id=uuid.uuid4())[1] == 0


def test_deal_filters_and_order(db_session: Session, ws_id):
    acc = mk_account(db_session, ws_id)
    old = mk_deal(db_session, ws_id, acc, "100% old", created_on=date(2025, 1, 1))
    new = mk_deal(db_session, ws_id, acc, "new", created_on=date(2026, 1, 1), lead_source="inbound")
    rows, total = deals.list_deals_page(db_session, ws_id)
    assert ([r.id for r in rows], total) == ([new.id, old.id], 2)
    assert deals.list_deals_page(db_session, ws_id, q="%")[0] == [old]
    assert deals.list_deals_page(db_session, ws_id, lead_source="inbound")[0] == [new]
    assert deals.list_deals_page(db_session, ws_id, stage="prospecting", limit=1)[1] == 2
    assert deals.deal_names(db_session, ws_id, [new.id]) == {new.id: ("Acme", None)}


def test_workspaces_with_counts_order(db_session: Session):
    workspaces.create_workspace(db_session, "zz-real", "Real")
    demo = workspaces.create_workspace(db_session, "aa-demo", "Demo", is_demo=True)
    mk_account(db_session, demo.id)
    rows = workspaces.list_workspaces_with_counts(db_session)
    slugs = [w.slug for w, *_ in rows]
    assert slugs.index("zz-real") < slugs.index("aa-demo")
    by = {w.slug: n for w, *n in rows}
    assert by["aa-demo"] == [1, 0, 0] and by["zz-real"] == [0, 0, 0]
