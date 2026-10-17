"""M2b demo data: roles, removed links, transcripts, themes and the isolation of the RNG streams."""

from __future__ import annotations

import re
from collections import defaultdict

import pytest

from app.demo import generator
from app.demo.generator import generate
from app.demo.names import ORG_TEMPLATE, ROLE_TITLES
from app.domain.enums import DealStage


def _stable(ds) -> str:
    parts = [ds.users, ds.accounts, ds.deals, ds.notes, ds.comments, ds.companies]
    blob = "\n".join(m.model_dump_json() for group in parts for m in group)
    blob += "\n".join(c.model_dump_json(exclude={"role", "reports_to_key"}) for c in ds.contacts)
    truth = ds.ground_truth.model_copy(
        update={"m2": None, "notes": [n for n in ds.ground_truth.notes if "decoy" not in n]}
    )
    return blob + truth.model_dump_json()


@pytest.mark.parametrize(("variant", "seed"), [("planted", 42), ("noise", 7)])
def test_m2_streams_do_not_move_m1_data(monkeypatch, variant, seed):
    full = generate(variant, seed)
    monkeypatch.setattr(
        generator, "_remove_links", lambda seed, contacts: ({c.key: None for c in contacts}, [])
    )
    monkeypatch.setattr(generator, "build_transcripts", lambda seed, **kw: ([], [], []))
    bare = generate(variant, seed)
    assert [d.model_dump_json() for d in full.deals] == [d.model_dump_json() for d in bare.deals]
    assert _stable(full) == _stable(bare)


def test_deterministic():
    a, b = generate("planted", 42), generate("planted", 42)
    assert [d.model_dump_json() for d in a.documents] == [d.model_dump_json() for d in b.documents]
    assert a.ground_truth.m2 == b.ground_truth.m2


def test_roles_and_removed_links():
    ds = generate("planted", 42)
    m2 = ds.ground_truth.m2
    assert set(m2.roles) == {c.key for c in ds.contacts}
    assert all(r in ROLE_TITLES for r in m2.roles.values())
    removed = set(m2.links_removed)
    accs = defaultdict(list)
    for c in ds.contacts:
        accs[c.account_key].append(c)
    hit = [a for a, cs in accs.items() if any(c.key in removed for c in cs)]
    assert 0.35 <= len(hit) / len(accs) <= 0.65
    for a, cs in accs.items():
        non_root = [c for c in cs if m2.org[c.key] is not None]
        if a in hit:  # all non-root links removed
            assert all(c.reports_to_key is None for c in cs)
            assert {c.key for c in non_root} == removed & {c.key for c in cs}
        else:
            assert all(c.reports_to_key == m2.org[c.key] for c in cs)
    for c in ds.contacts:  # the true tree follows the template
        j = int(c.key.rsplit("-c", 1)[1])
        parent = ORG_TEMPLATE[j][1]
        assert (m2.org[c.key] is None) == (parent is None)


def test_transcripts_shape_and_dates():
    ds = generate("planted", 42)
    assert 150 <= len(ds.documents) <= 170
    deals = {d.key: d for d in ds.deals}
    contacts = {c.key: c for c in ds.contacts}
    owners = {u.key: u.display_name for u in ds.users}
    assert len({d.deal_key for d in ds.documents}) == len(ds.documents)
    n_fr = sum(d.language == "fr" for d in ds.documents)
    assert 0.55 <= n_fr / len(ds.documents) <= 0.65
    for doc in ds.documents:
        deal = deals[doc.deal_key]
        assert deal.account_key == doc.account_key
        assert deal.created_on <= doc.meeting_date
        if deal.closed_on:
            assert doc.meeting_date <= deal.closed_on
        lines = doc.text.strip().split("\n")
        assert 6 <= len(lines) <= 16
        names = {c.full_name for c in contacts.values() if c.account_key == doc.account_key}
        speakers = {ln.split(": ", 1)[0] for ln in lines}
        assert owners[deal.owner_key] in speakers
        customers = speakers - {owners[deal.owner_key]}
        assert 1 <= len(customers) <= 3 and customers <= names


def test_planted_effects():
    ds = generate("planted", 42)
    lost = {d.key for d in ds.deals if d.stage is DealStage.CLOSED_LOST}
    ms = ds.ground_truth.m2.meetings
    L = [m for m in ms if m.deal_key in lost]
    O = [m for m in ms if m.deal_key not in lost]  # noqa: E741
    pl = sum("price_objection" in m.themes for m in L) / len(L)
    po = sum("price_objection" in m.themes for m in O) / len(O)
    assert 0.55 <= pl <= 0.75 and 0.12 <= po <= 0.28
    seg = {a.key: a.segment.value for a in ds.accounts}
    ent = [m for m in ms if seg[m.account_key] == "enterprise"]
    rest = [m for m in ms if seg[m.account_key] != "enterprise"]
    se = sum("security_gdpr" in m.themes for m in ent) / len(ent)
    sr = sum("security_gdpr" in m.themes for m in rest) / len(rest)
    assert se > 1.5 * sr
    assert all(t in ds.ground_truth.m2.theme_ids for m in ms for t in m.themes)


def test_org_statements_signals_and_decoys():
    ds = generate("planted", 42)
    m2 = ds.ground_truth.m2
    docs = {d.key: d for d in ds.documents}
    name = {c.key: c.full_name for c in ds.contacts}
    n_stmt = 0
    for m in m2.meetings:
        text = docs[m.document_key].text
        for who, mgr in m.org_statements:
            n_stmt += 1
            assert who in m2.links_removed and m2.org[who] == mgr
            assert name[mgr] in text
            assert any(
                ln.startswith(f"{name[who]}: ") and name[mgr] in ln for ln in text.split("\n")
            )
        for who, kind in m.signals:
            assert kind in {"champion", "blocker", "decision_maker"}
    assert n_stmt >= 0.38 * len(m2.links_removed)
    kinds = [k for m in m2.meetings for _, k in m.signals]
    assert kinds.count("champion") > kinds.count("blocker")
    assert any("decoy" in n for n in ds.ground_truth.notes)
    assert (
        len(re.findall(r"board|conseil d'administration", " ".join(d.text for d in ds.documents)))
        == 5
    )


_THEME_WORDS = {
    "price_objection": r"prix|tarif|co[uû]t|cher|chère|remise|r[ée]duction|budget|pricing|expensive"
    r"|discount|cost|price|cheaper|licences",
    "integration_need": r"int[ée]gration|Salesforce|HubSpot|API|connecteur|connector|sync",
    "security_gdpr": r"RGPD|GDPR|s[ée]curit|security|SOC 2|h[ée]bergement|hosted|hosting",
    "competitor_vendara": r"Vendara",
    "timing_freeze": r"gel des budgets|budget freeze|trimestre|quarter",
}


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.?!]) ", text)


def _customer_sentences(ds) -> list[str]:
    names = {c.full_name for c in ds.contacts}
    out = []
    for d in ds.documents:
        for ln in d.text.strip().split("\n"):
            who, text = ln.split(": ", 1)
            if who in names:
                out += _sentences(text)
    return out


def test_transcripts_are_not_repetitive():
    ds = generate("planted", 42)
    sents = _customer_sentences(ds)
    assert len(set(sents)) / len(sents) >= 0.70
    top = max(sents.count(s) for s in set(sents))
    assert top <= 15  # fixed signal sentences are the most repeated (was 78)


def test_theme_phrasing_variety_and_one_theme_per_sentence():
    from app.demo.transcripts import THEME_TEXT

    for theme, by_lang in THEME_TEXT.items():
        for lang, phrases in by_lang.items():
            assert len(set(phrases)) >= 8, (theme, lang)
            for p in phrases:
                assert re.search(_THEME_WORDS[theme], p), p
                for other, rx in _THEME_WORDS.items():
                    if other == theme or {theme, other} == {"price_objection", "timing_freeze"}:
                        continue  # "budget" is shared vocabulary of the contract
                    assert not re.search(rx, p), (theme, other, p)
    ds = generate("planted", 42)
    docs = {d.key: d for d in ds.documents}
    used: dict[str, set[str]] = defaultdict(set)
    for m in ds.ground_truth.m2.meetings:
        for s in _sentences(" ".join(docs[m.document_key].text.split("\n"))):
            for theme in m.themes:
                if re.search(_THEME_WORDS[theme], s):
                    used[theme].add(s)
    for theme in ("price_objection", "integration_need", "security_gdpr"):
        assert len(used[theme]) >= 8, theme
