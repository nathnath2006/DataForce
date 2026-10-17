from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.db.models import Account, Comment, Contact, Deal, Note, Workspace
from app.demo.check import check_against_truth
from app.demo.generator import generate
from app.demo.loader import load_dataset
from app.services import analytics, contacts, notes, workspaces
from app.services.errors import AlreadyExistsError

pytestmark = pytest.mark.integration


def _count(session, model, ws_id):
    return session.scalar(
        select(func.count()).select_from(model).where(model.workspace_id == ws_id)
    )


def test_load_exact_counts_and_org_charts(db_session):
    ds = generate("planted", 42)
    res = load_dataset(db_session, ds, workspace_slug="demo-planted")
    ws_id = res["workspace_id"]
    ws = db_session.get(Workspace, ws_id)
    assert ws.is_demo
    assert res["accounts"] == len(ds.accounts) == _count(db_session, Account, ws_id)
    assert res["contacts"] == len(ds.contacts) == _count(db_session, Contact, ws_id)
    assert res["deals"] == len(ds.deals) == _count(db_session, Deal, ws_id)
    assert _count(db_session, Note, ws_id) == len(ds.notes)
    assert _count(db_session, Comment, ws_id) == len(ds.comments)
    assert all(
        d.source == "demo"
        for d in db_session.scalars(select(Deal).where(Deal.workspace_id == ws_id))
    )

    # one root per account, and the reporting lines match the dataset
    for acc in db_session.scalars(select(Account).where(Account.workspace_id == ws_id)).all()[:10]:
        chart = contacts.org_chart(db_session, ws_id, acc.id)
        assert sum(1 for _, mgr in chart if mgr is None) == 1

    # corrected notes: current_notes shows the latest version only
    n_corr = res["note_corrections"]
    assert n_corr > 0
    all_contacts = db_session.scalars(select(Contact.id).where(Contact.workspace_id == ws_id)).all()
    current = sum(len(notes.current_notes(db_session, ws_id, cid)) for cid in all_contacts)
    assert current == len(ds.notes) - n_corr


def test_replace_and_duplicate(db_session):
    ds = generate("noise", 1, n_deals=60)
    first = load_dataset(db_session, ds, workspace_slug="demo-x")
    with pytest.raises(AlreadyExistsError):
        load_dataset(db_session, ds, workspace_slug="demo-x")
    second = load_dataset(db_session, ds, workspace_slug="demo-x", replace=True)
    assert second["workspace_id"] != first["workspace_id"]
    assert workspaces.get_workspace_by_slug(db_session, "demo-x").id == second["workspace_id"]
    assert _count(db_session, Deal, second["workspace_id"]) == 60
    assert _count(db_session, Deal, first["workspace_id"]) == 0


def test_db_roundtrip_through_engine(db_session):
    ds = generate("planted", 42)
    res = load_dataset(db_session, ds, workspace_slug="demo-scan")
    report = analytics.run_scan(db_session, res["workspace_id"])
    assert report.n_deals == len(ds.deals)
    assert check_against_truth(report, ds.ground_truth).passed


def test_replace_refuses_a_non_demo_workspace(db_session):
    from app.services.errors import InvalidInputError

    workspaces.create_workspace(db_session, "real-ws", "Real", is_demo=False)
    ds = generate("noise", 1, n_deals=60)
    with pytest.raises(InvalidInputError):
        load_dataset(db_session, ds, workspace_slug="real-ws", replace=True)
    assert workspaces.get_workspace_by_slug(db_session, "real-ws") is not None
