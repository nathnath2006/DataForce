"""SR17-02/03: the 'manager named earlier' mention is vetted, near and bounded."""

from __future__ import annotations

import uuid

from app.orgchart import meeting_ai
from app.orgchart.meeting_ai import AiItem, Turn
from app.orgchart.meetings import ContactRef

DOC = uuid.uuid4()
ANA, BOB, ZOE = (uuid.uuid4() for _ in range(3))
C = [ContactRef(ANA, "Ana Dupont"), ContactRef(BOB, "Bob Martin"), ContactRef(ZOE, "Zoe Bernard")]
S = "I report to her every week."


def run(doc: str):
    at = doc.index(S)
    t = Turn(DOC, uuid.uuid4(), "Ana", ANA, at, doc[at:])
    it = AiItem(kind="reports_to", contact="Ana Dupont", manager="Bob Martin", quote=S)
    kept, _ = meeting_ai.verify([it], [t], C, doc)
    for v in kept:
        ev = v.evidence
        if "manager_excerpt" in ev:
            assert doc[ev["manager_char_start"] : ev["manager_char_end"]] == ev["manager_excerpt"]
            assert len(ev["manager_excerpt"]) <= 300
            assert ev["manager_char_end"] <= ev["char_start"]
    return kept


def test_a_real_earlier_mention_is_kept():
    kept = run("Zoe Bernard: Bob Martin runs the sales team here.\nAna Dupont: " + S)
    assert len(kept) == 1
    assert "Bob Martin runs" in kept[0].evidence["manager_excerpt"]


def test_speaker_label_is_not_a_mention():
    assert run("Bob Martin: Hello everyone, let us start.\nAna Dupont: " + S) == []
    assert run("**Bob Martin:** Hello everyone, let us start.\nAna Dupont: " + S) == []


def test_hypothetical_negated_and_past_decoys_are_skipped():
    for line in (
        "Zoe Bernard: If Bob Martin were the boss we would be fine.",
        "Zoe Bernard: Bob Martin is not our manager at all.",
        "Zoe Bernard: Bob Martin used to be our manager.",
    ):
        assert run(line + "\nAna Dupont: " + S) == [], line


def test_nearest_passing_mention_wins_over_a_nearer_decoy():
    doc = (
        "Zoe Bernard: Bob Martin runs the sales team.\n"
        "Zoe Bernard: If Bob Martin were the boss we would be fine.\nAna Dupont: " + S
    )
    kept = run(doc)
    assert len(kept) == 1 and "runs the sales team" in kept[0].evidence["manager_excerpt"]


def test_mention_beyond_40_turns_is_ignored():
    filler = "Zoe Bernard: filler line here.\n"
    base = "Zoe Bernard: Bob Martin runs the sales team.\n"
    assert run(base + filler * 60 + "Ana Dupont: " + S) == []
    assert len(run(base + filler * 30 + "Ana Dupont: " + S)) == 1


def test_long_sentence_is_windowed_around_the_name():
    big = "Zoe Bernard: " + "x " * 5000 + "Bob Martin runs " + "y " * 5000 + "\nAna Dupont: " + S
    kept = run(big)
    assert len(kept) == 1
    ex = kept[0].evidence["manager_excerpt"]
    assert "Bob Martin" in ex and 0 < len(ex) <= 300
