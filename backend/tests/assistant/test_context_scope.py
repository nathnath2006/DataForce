"""Context scopes: account / deal widen to the whole company; focus first; capping; isolation."""

from __future__ import annotations

from datetime import date

import pytest

from app.assistant.ask import check_answer
from app.assistant.context import build_context
from app.db.models import (
    Account,
    Company,
    Contact,
    ContactChannel,
    Deal,
    Document,
    Note,
    Workspace,
)
from app.services.errors import NotFoundError

pytestmark = pytest.mark.integration

SECRET = "secret.person@example.com"


@pytest.fixture
def world(db_session):
    s = db_session
    ws = Workspace(slug="ctx1", name="Ctx")
    other_ws = Workspace(slug="ctx2", name="Other")
    s.add_all([ws, other_ws])
    s.flush()
    co = Company(workspace_id=ws.id, name="Acme Group")
    s.add(co)
    s.flush()
    accs = [
        Account(workspace_id=ws.id, name=n, company_id=co.id)
        for n in ("Acme", "Acme Sub", "Acme Lab")
    ]
    s.add_all(accs)
    s.flush()
    boss = Contact(workspace_id=ws.id, account_id=accs[1].id, full_name="Bea Boss", title="CEO")
    s.add(boss)
    s.flush()
    sis = Contact(
        workspace_id=ws.id,
        account_id=accs[1].id,
        full_name="Sis Contact",
        title="CFO",
        title_function="finance",
        title_seniority="c_level",
        reports_to_id=boss.id,
    )
    mine = Contact(workspace_id=ws.id, account_id=accs[0].id, full_name="Jo Martin", title="CTO")
    s.add_all([sis, mine])
    s.flush()
    s.add(
        ContactChannel(
            workspace_id=ws.id, contact_id=sis.id, kind="email", value_enc=SECRET, provider="fake"
        )
    )
    deals = [
        Deal(
            workspace_id=ws.id,
            account_id=a.id,
            name=f"Deal {a.name}",
            amount_eur=1000 * (i + 1),
            created_on=date(2026, 1, 1),
        )
        for i, a in enumerate(accs)
    ]
    s.add_all(deals)
    s.flush()
    s.add(
        Document(
            workspace_id=ws.id,
            account_id=accs[1].id,
            deal_id=deals[1].id,
            title="Kickoff <b>x</b>",
            meeting_date=date(2026, 2, 2),
            sha256="a" * 64,
            size_bytes=1,
            text="t",
            n_chars=1,
        )
    )
    s.flush()
    return {
        "s": s,
        "ws": ws,
        "other": other_ws,
        "accs": accs,
        "deals": deals,
        "co": co,
        "sis": sis,
        "mine": mine,
    }


def ctx_of(w, kind, id_, max_chars=100_000):
    return build_context(w["s"], w["ws"].id, kind, id_, max_chars=max_chars)[0]


def test_account_covers_sister_accounts(world):
    ctx = ctx_of(world, "account", world["accs"][0].id)
    text = ctx.render()
    assert "You are on the account Acme" in ctx.items[0].text
    assert "Sis Contact" in text and "Deal Acme Sub" in text and "Deal Acme Lab" in text
    assert "title: CFO | function: finance | seniority: c_level | reports to: Bea Boss" in text
    assert "Kickoff" in text and "[G1]" in text and "deal Deal Acme Sub" in text
    # focus first
    assert text.index("Jo Martin") < text.index("Sis Contact")
    assert text.index("Deal Acme |") < text.index("Deal Acme Sub")


def test_deal_scope_focuses_its_deal(world):
    ctx = ctx_of(world, "deal", world["deals"][1].id)
    assert ctx.items[0].text == "You are on the deal Deal Acme Sub of account Acme Sub"
    d1 = next(i for i in ctx.items if i.ref == "D1")
    assert d1.text.startswith("Deal Acme Sub")
    assert next(i for i in ctx.items if i.ref == "C1").text.startswith("Bea Boss")


def test_no_company_only_the_account(world):
    s = world["s"]
    lone = Account(workspace_id=world["ws"].id, name="Lone")
    s.add(lone)
    s.flush()
    assert "Acme" not in ctx_of(world, "account", lone.id).render()


def test_isolation_and_channels(world):
    s = world["s"]
    with pytest.raises(NotFoundError):
        build_context(s, world["other"].id, "deal", world["deals"][0].id, max_chars=10_000)
    with pytest.raises(NotFoundError):
        build_context(s, world["other"].id, "account", world["accs"][0].id, max_chars=10_000)
    assert SECRET not in ctx_of(world, "account", world["accs"][0].id).render()


def test_meeting_title_wrapped_untrusted(world):
    text = ctx_of(world, "company", world["co"].id).render()
    assert '<source id="G1">' in text and "<b>" not in text and "&lt;b&gt;" in text


def test_capping_order_focus_survives(world):
    s, ws = world["s"], world["ws"]
    for i in range(20):
        s.add(Note(workspace_id=ws.id, contact_id=world["sis"].id, body=f"other {i} " + "w" * 500))
    s.add(Note(workspace_id=ws.id, contact_id=world["mine"].id, body="focus note " + "w" * 100))
    s.flush()
    ctx = ctx_of(world, "account", world["accs"][0].id, max_chars=3000)
    text = ctx.render()
    assert len(text) <= 3000 and ctx.truncated
    assert "focus note" in text and "Jo Martin" in text and "Deal Acme |" in text
    assert "older notes of other accounts" in text
    ctx2 = ctx_of(world, "account", world["accs"][0].id, max_chars=1800)
    t2 = ctx2.render()
    assert "Jo Martin" in t2 and "Deal Acme |" in t2 and "Sis Contact" not in t2


def test_number_check_still_flags_invented(world):
    ctx = ctx_of(world, "account", world["accs"][0].id)
    out = check_answer("Acme Sub is worth 2000.00 [D2] but 777 deals [G1].", ctx)
    assert out.unverified_numbers == ["777"]
    assert [c["kind"] for c in out.citations] == ["deal", "meeting"]
