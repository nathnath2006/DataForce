"""FR/EN meeting patterns, name resolution and exact-excerpt offsets (no DB)."""

from __future__ import annotations

import uuid

import pytest

from app.orgchart import meetings
from app.orgchart.meetings import ChunkRec, ContactRef

DOC = uuid.uuid4()
ANA, BOB, MARIE_A, MARIE_B, ZOE = (uuid.uuid4() for _ in range(5))
CONTACTS = [
    ContactRef(ANA, "Ana Dupont"),
    ContactRef(BOB, "Bob Martin-Lévy"),
    ContactRef(MARIE_A, "Marie Curie"),
    ContactRef(MARIE_B, "Marie Durand"),
    ContactRef(ZOE, "Zoé Bernard"),
]


def extract(text: str, speaker=ANA, prefix="Ana: "):
    doc = prefix + text
    chunk = ChunkRec(DOC, uuid.uuid4(), "Ana", speaker, len(prefix), len(doc), text)
    return meetings.extract([chunk], CONTACTS, {DOC: doc}), doc


@pytest.mark.parametrize(
    ("text", "manager", "pattern"),
    [
        ("I report to Bob Martin-Lévy.", BOB, "en_i_report_to"),
        ("I report to Zoe", ZOE, "en_i_report_to"),
        ("My boss is Bob", BOB, "en_my_boss_is"),
        ("my line manager is Zoé Bernard", ZOE, "en_my_boss_is"),
        ("Zoe is my manager", ZOE, "en_is_my_boss"),
        ("Bob Martin-Lévy is my boss.", BOB, "en_is_my_boss"),
        ("Je reporte à Zoé.", ZOE, "fr_je_reporte_a"),
        ("Mon n+1 c'est Bob.", BOB, "fr_mon_manager_est"),
        ("Mon responsable est Zoé Bernard", ZOE, "fr_mon_manager_est"),
        ("Mon chef c’est Bob", BOB, "fr_mon_manager_est"),
        ("Bob est mon manager", BOB, "fr_est_mon_manager"),
        ("Zoé est mon n+1.", ZOE, "fr_est_mon_manager"),
        ("Je suis sous la responsabilité de Bob.", BOB, "fr_sous_la_responsabilite"),
    ],
)
def test_reports_to_patterns(text, manager, pattern):
    found, doc = extract(text)
    assert len(found) == 1
    f = found[0]
    assert (f.kind, f.contact_id, f.manager_id, f.pattern) == ("reports_to", ANA, manager, pattern)
    ev = f.evidence
    assert doc[ev["char_start"] : ev["char_end"]] == ev["excerpt"]


@pytest.mark.parametrize(
    "text",
    [
        "I'll push this to the board.",
        "I will champion it.",
        "Je vais pousser le dossier.",
        "Je vais porter le projet",
        "Je vais défendre ça !",
    ],
)
def test_champion_patterns(text):
    found, _ = extract(text)
    assert [(f.kind, f.contact_id) for f in found] == [("champion", ANA)]


@pytest.mark.parametrize(
    ("text", "who"),
    [
        ("Bob is against the plan.", BOB),
        ("Zoe is not convinced yet.", ZOE),
        ("Bob is blocking this.", BOB),
        ("Zoé bloque le budget.", ZOE),
        ("Bob est contre.", BOB),
        ("Zoé n'est pas convaincue.", ZOE),
        ("Bob n’est pas convaincu", BOB),
    ],
)
def test_blocker_patterns(text, who):
    found, _ = extract(text)
    assert [(f.kind, f.contact_id) for f in found] == [("blocker", who)]


@pytest.mark.parametrize(
    ("text", "who"),
    [
        ("Zoe makes the final decision.", ZOE),
        ("Bob will make the call.", BOB),
        ("Zoé has the decision.", ZOE),
        ("C'est Zoé qui décide.", ZOE),
        ("C'est Bob Martin-Lévy qui signe", BOB),
        ("c'est Bob qui valide et c'est Zoé qui tranche.", BOB),
    ],
)
def test_decision_maker_patterns(text, who):
    found, _ = extract(text)
    assert found and found[0].kind == "decision_maker" and found[0].contact_id == who


def test_unmatched_and_ambiguous_names_give_nothing():
    assert extract("I report to Carlos.")[0] == []
    assert extract("Marie is against the plan.")[0] == []  # two Maries: first name not unique
    assert extract("Marie Curie is against the plan.")[0][0].contact_id == MARIE_A
    assert extract("Je reporte à personne.")[0] == []


def test_self_report_is_ignored():
    assert extract("I report to Ana.")[0] == []


def test_speaker_must_be_a_matched_contact():
    assert extract("I report to Bob.", speaker=None)[0] == []
    assert extract("I report to Bob.", speaker=uuid.uuid4())[0] == []


def test_excerpt_is_the_exact_sentence_with_offsets():
    text = "We met last week. Honestly, I report to Bob Martin-Lévy! Anyway, next topic."
    found, doc = extract(text)
    ev = found[0].evidence
    assert ev["excerpt"] == "Honestly, I report to Bob Martin-Lévy!"
    assert doc[ev["char_start"] : ev["char_end"]] == ev["excerpt"]
    assert ev["speaker"] == "Ana"


def test_offsets_not_matching_document_are_dropped():
    chunk = ChunkRec(DOC, uuid.uuid4(), "Ana", ANA, 0, 20, "I report to Bob.")
    assert meetings.extract([chunk], CONTACTS, {DOC: "something else entirely"}) == []


def test_fold_keeps_length():
    s = "Zoé œuvre à l’ONU – İstanbul ß"
    assert len(meetings.fold(s)) == len(s)
