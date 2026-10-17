"""Demo companies: grouped by name family, synthetic, and the rest of the dataset untouched."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db.models import Account, Company
from app.demo import generator
from app.demo.generator import generate
from app.demo.loader import load_dataset


def _digest(ds) -> str:
    parts = [
        ds.users,
        ds.accounts,
        ds.contacts,
        ds.deals,
        ds.notes,
        ds.comments,
    ]
    blob = "\n".join(m.model_dump_json() for group in parts for m in group)
    blob += ds.ground_truth.model_dump_json()
    return hashlib.sha256(blob.encode()).hexdigest()


@pytest.mark.parametrize(("variant", "seed"), [("planted", 42), ("noise", 7)])
def test_companies_do_not_move_other_data(monkeypatch, variant, seed):
    with_companies = generate(variant, seed)
    monkeypatch.setattr(generator, "_build_companies", lambda seed, accounts: ([], {}))
    without = generate(variant, seed)
    assert without.companies == []
    assert [d.model_dump_json() for d in with_companies.deals] == [
        d.model_dump_json() for d in without.deals
    ]
    assert _digest(with_companies) == _digest(without)


def test_grouping_and_synthetic_content():
    ds = generate("planted", 42)
    assert ds.companies and generate("planted", 42).companies == ds.companies  # deterministic
    names = {a.key: a.name for a in ds.accounts}
    assert set(ds.account_company) == set(names)  # every account has a company
    by_co: dict[str, set[str]] = {}
    for akey, ckey in ds.account_company.items():
        by_co.setdefault(ckey, set()).add(names[akey].split()[0])
    assert all(len(words) == 1 for words in by_co.values())  # one name family per company
    assert len(by_co) == len(ds.companies) == len({w for s in by_co.values() for w in s})
    assert any(
        sum(1 for c in ds.account_company.values() if c == k) > 1 for k in by_co
    )  # at least one company groups several accounts
    forms = {"SAS", "SARL", "SA", "SASU"}
    for co in ds.companies:
        assert co.name.rsplit(" ", 1)[1] in forms
        assert co.country == "FR" and co.source.value == "demo"
        assert not hasattr(co, "siren")
        assert co.address_line and co.postal_code and co.city


def test_alderon_family_shares_a_company():
    ds = generate("planted", 42)
    # build a dataset where the family is certain: re-group three Alderon accounts
    accs = [
        a.model_copy(update={"name": n})
        for a, n in zip(
            ds.accounts[:3], ["Alderon Conseil", "Alderon Digital", "Alderon Group"], strict=True
        )
    ]
    companies, link = generator._build_companies(42, accs)
    assert len(companies) == 1 and companies[0].name.startswith("Alderon ")
    assert set(link.values()) == {companies[0].key}


@pytest.mark.integration
def test_loader_creates_companies(db_session):
    ds = generate("planted", 42)
    res = load_dataset(db_session, ds, workspace_slug="demo-co")
    ws_id = res["workspace_id"]
    assert res["companies"] == len(ds.companies)
    cos = list(db_session.scalars(select(Company).where(Company.workspace_id == ws_id)))
    assert len(cos) == len(ds.companies)
    assert all(c.siren is None and c.source == "demo" for c in cos)
    accs = list(db_session.scalars(select(Account).where(Account.workspace_id == ws_id)))
    assert all(a.company_id is not None for a in accs)
    assert {a.company_id for a in accs} == {c.id for c in cos}


def test_demo_notes_and_comments_have_past_dates():
    from app.demo.generator import REFERENCE_DATE, generate

    ds = generate("planted", 42)
    end = datetime.combine(REFERENCE_DATE, datetime.max.time(), tzinfo=UTC)
    for rows in (ds.notes, ds.comments):
        when = {r.key: r.created_at for r in rows}
        assert all(r.created_at is not None and r.created_at <= end for r in rows)
        assert len({r.created_at.date() for r in rows}) > len(rows) // 2  # spread, not one day
        for r in rows:
            if r.corrects_key:
                assert r.created_at >= when[r.corrects_key]
