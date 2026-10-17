from __future__ import annotations

from datetime import date

import pytest

from app.db.models import Account, Comment, Company, Contact, Deal, Note, Workspace
from app.flows.sources.crm import CRM_COLUMNS, load_crm_table

pytestmark = pytest.mark.integration


@pytest.fixture
def world(db_session, ws_id):
    s = db_session
    co = Company(workspace_id=ws_id, name="Acme Group", siren="123456789", city="Lyon")
    s.add(co)
    s.flush()
    a1 = Account(workspace_id=ws_id, name="Acme FR", company_id=co.id, segment="smb")
    a2 = Account(workspace_id=ws_id, name="Acme DE", company_id=co.id)
    s.add_all([a1, a2])
    s.flush()
    boss = Contact(workspace_id=ws_id, account_id=a1.id, full_name="Boss")
    s.add(boss)
    s.flush()
    s.add(Contact(workspace_id=ws_id, account_id=a1.id, full_name="Dev", reports_to_id=boss.id))
    s.flush()
    n1 = Note(workspace_id=ws_id, contact_id=boss.id, body="v1")
    s.add(n1)
    s.flush()
    s.add(Note(workspace_id=ws_id, contact_id=boss.id, body="v2", corrects_id=n1.id))
    s.add(Comment(workspace_id=ws_id, account_id=a2.id, body="c"))
    s.add_all(
        [
            Deal(
                workspace_id=ws_id,
                account_id=a1.id,
                name="W",
                amount_eur=100,
                stage="closed_won",
                created_on=date(2025, 1, 1),
                closed_on=date(2025, 1, 11),
            ),
            Deal(
                workspace_id=ws_id,
                account_id=a1.id,
                name="L",
                amount_eur=50,
                stage="closed_lost",
                created_on=date(2025, 2, 1),
                closed_on=date(2025, 2, 2),
            ),
            Deal(
                workspace_id=ws_id,
                account_id=a2.id,
                name="O",
                amount_eur=7,
                stage="proposal",
                created_on=date(2025, 3, 1),
            ),
        ]
    )
    other = Workspace(slug="other-ws", name="O")
    s.add(other)
    s.flush()
    s.add(Account(workspace_id=other.id, name="Foreign"))
    s.flush()
    return ws_id


def test_columns_match_contract(db_session, world):
    for table, cols in CRM_COLUMNS.items():
        df = load_crm_table(db_session, world, table, 1000)
        assert list(df.columns) == [c for c, _ in cols]


def test_deals(db_session, world):
    df = load_crm_table(db_session, world, "deals", 1000).set_index("deal_name")
    assert len(df) == 3
    assert df.loc["W", "is_won"] is True or df.loc["W", "is_won"] == True  # noqa: E712
    assert df.loc["L", "is_won"] == False  # noqa: E712
    assert df.loc["O", "is_won"] is None or df["is_won"].isna()["O"]
    assert df.loc["W", "cycle_days"] == 10 and df.loc["W", "amount_eur"] == 100.0
    assert df.loc["O", "is_closed"] == False  # noqa: E712
    assert df.loc["W", "company_name"] == "Acme Group"


def test_accounts_contacts_companies(db_session, world):
    acc = load_crm_table(db_session, world, "accounts", 1000).set_index("account_name")
    assert "Foreign" not in acc.index
    fr = acc.loc["Acme FR"]
    assert (fr.n_contacts, fr.n_deals, fr.n_open_deals, fr.n_won, fr.n_lost) == (2, 2, 0, 1, 1)
    assert fr.won_amount_eur == 100.0
    con = load_crm_table(db_session, world, "contacts", 1000).set_index("full_name")
    assert con.loc["Boss", "n_direct_reports"] == 1 and con.loc["Boss", "n_notes"] == 1
    assert con.loc["Dev", "reports_to_name"] == "Boss"
    comp = load_crm_table(db_session, world, "companies", 1000).iloc[0]
    assert (comp.company_name, comp.n_accounts, comp.n_deals) == ("Acme Group", 2, 3)
    assert comp.last_interaction is not None and str(comp.last_interaction) != "NaT"


def test_cap_flag(db_session, world):
    df = load_crm_table(db_session, world, "deals", 2)
    assert len(df) == 2 and df.attrs["capped"] is True
