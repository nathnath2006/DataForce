"""Rules R0-R3 on plain records (no DB)."""

from __future__ import annotations

import uuid

from app.orgchart import rules
from app.orgchart.rules import Person

ACC = uuid.uuid4()


def p(name: str, function: str, seniority: str, manager=None, acc=ACC) -> Person:
    return Person(uuid.uuid5(uuid.NAMESPACE_DNS, name), acc, name, function, seniority, manager)


def ids(*people: Person):
    return {x.title: x for x in people}


def run(people, rejected=()):
    return {x.contact_id: x for x in rules.propose_for_account(people, rejected)}


def test_r0_root_needs_exactly_one_executive_c_level():
    ceo = p("ceo", "executive", "c_level")
    assert rules.find_root([ceo, p("cfo", "finance", "c_level")]) == ceo
    assert rules.find_root([ceo, p("ceo2", "executive", "c_level")]) is None
    assert rules.find_root([p("cfo", "finance", "c_level")]) is None


def test_r1_c_level_to_ceo():
    ceo, cfo = p("ceo", "executive", "c_level"), p("cfo", "finance", "c_level")
    out = run([ceo, cfo])
    assert ceo.id not in out
    got = out[cfo.id]
    assert (got.rule, got.manager_id) == ("c_level_to_ceo", ceo.id)
    assert got.evidence["contact_title"] == "cfo" and got.evidence["manager_title"] == "ceo"
    assert got.evidence["explanation"]


def test_r2_next_level_picks_smallest_rank_above():
    vp = p("vp", "sales", "vp")
    head = p("head", "sales", "head")
    mgr = p("mgr", "sales", "manager")
    rep = p("rep", "sales", "individual")
    out = run([vp, head, mgr, rep])
    assert out[rep.id].manager_id == mgr.id and out[rep.id].rule == "next_level_in_function"
    assert out[mgr.id].manager_id == head.id
    assert out[head.id].manager_id == vp.id


def test_r2_ambiguous_lists_candidates():
    a, b = p("m1", "sales", "manager"), p("m2", "sales", "manager")
    rep = p("rep", "sales", "individual")
    out = run([a, b, rep])
    got = out[rep.id]
    assert got.ambiguous and got.manager_id is None
    assert set(got.candidates) == {a.id, b.id}


def test_r2_other_function_is_ignored_and_r3_goes_to_root():
    ceo = p("ceo", "executive", "c_level")
    head = p("headm", "marketing", "head")
    mgr = p("mgrs", "sales", "manager")
    out = run([ceo, head, mgr])
    assert out[head.id].rule == "senior_to_ceo" and out[head.id].manager_id == ceo.id
    assert mgr.id not in out  # below head, nobody above in sales: no proposal


def test_r3_needs_a_root():
    assert run([p("head", "sales", "head")]) == {}


def test_unknown_classes_and_existing_links_are_skipped():
    ceo = p("ceo", "executive", "c_level")
    unknown = p("u", "unknown", "head")
    unknown_s = p("us", "sales", "unknown")
    linked = p("linked", "sales", "head", manager=ceo.id)
    assert run([ceo, unknown, unknown_s, linked]) == {}


def test_no_cycle_against_existing_links():
    # boss is a manual subordinate of rep: proposing rep -> boss would close a loop.
    boss0 = p("boss", "sales", "manager")
    rep = p("rep", "sales", "individual")
    boss = Person(boss0.id, ACC, "boss", "sales", "manager", rep.id)
    assert run([boss, rep]) == {}


def test_no_cross_account_proposal():
    other = uuid.uuid4()
    here = p("rep", "sales", "individual")
    there = p("mgr", "sales", "manager", acc=other)
    assert run([here, there]) == {}


def test_no_reproposal_after_rejection():
    mgr, rep = p("mgr", "sales", "manager"), p("rep", "sales", "individual")
    assert rep.id in run([mgr, rep])
    assert run([mgr, rep], rejected=[(rep.id, mgr.id)]) == {}


def test_would_cycle():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    parents = {a: b, b: c, c: None}
    assert rules.would_cycle(parents, c, a)
    assert not rules.would_cycle(parents, a, c)
