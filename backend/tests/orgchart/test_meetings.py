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


# --- SR12-04: a first name never matches a longer, different name ------------------------------
def test_first_name_does_not_match_longer_names():
    only = [
        ContactRef(ANA, "Ana Dupont"),
        ContactRef(MARIE_A, "Marie Dupont"),
        ContactRef(BOB, "Jean Dupont"),
    ]

    def found(text):
        doc = "Ana: " + text
        chunk = ChunkRec(DOC, uuid.uuid4(), "Ana", ANA, 5, len(doc), text)
        return [f.manager_id for f in meetings.extract([chunk], only, {DOC: doc})]

    assert found("My manager is Marie Curie.") == []
    assert found("I report to Jean-Pierre Martin.") == []
    assert found("I report to Anne-Marie Roux.") == []
    assert found("I report to Marie Dupont.") == [MARIE_A]
    assert found("I report to Marie.") == [MARIE_A]
    assert found("Je reporte à Marie, depuis un an.") == [MARIE_A]
    assert found("I report to Jean Dupont-Martin.") == []
    assert found("I report to Jean. Then we met.") == [BOB]


def test_conditional_report_statement_is_refused():
    import re

    from app.orgchart.meetings import _HYPOTHETICAL

    assert _HYPOTHETICAL.search("if i report to paul, he will say no")
    assert _HYPOTHETICAL.search("si je reporte a paul")
    assert not re.search(_HYPOTHETICAL, "i report to paul")


@pytest.mark.parametrize(
    ("text", "manager"),
    [
        ("Moi je suis rattachée directement à Bob, le PDG.", BOB),
        ("Je suis rattaché hiérarchiquement à Zoé.", ZOE),
        ("Bob, mon N+1, valide tout avant l'envoi.", BOB),
        ("I work under Bob.", BOB),
        ("I report directly into Zoe.", ZOE),
        ("I report directly to Bob.", BOB),
        ("My boss, Bob, wants a quote by Friday.", BOB),
        ("Bob, my boss, signed off on it.", BOB),
        ("Bob, who is my manager, was there.", BOB),
        ("Bob, c'est ma directrice, je suis dans son équipe.", BOB),
        ("Zoé, ma cheffe, est d'accord.", ZOE),
        ("Mon manager, Bob, est en congé.", BOB),
        ("Ma responsable hiérarchique, Zoé, a validé.", ZOE),
        ("C'est Bob qui gère mon équipe.", BOB),
        ("Bob manages my team.", BOB),
        ("Je travaille sous Zoé depuis deux ans.", ZOE),
        ("Je suis sous la direction de Bob.", BOB),
        ("Je suis dans l'équipe de Zoé.", ZOE),
        ("Our CFO Bob is fine but my manager Zoe decides.", ZOE),
    ],
)
def test_reports_to_generalised(text, manager):
    found, doc = extract(text)
    rep = [f for f in found if f.kind == "reports_to"]
    assert len(rep) == 1 and rep[0].contact_id == ANA and rep[0].manager_id == manager
    ev = rep[0].evidence
    assert doc[ev["char_start"] : ev["char_end"]] == ev["excerpt"]


@pytest.mark.parametrize(
    "text",
    [
        "If I report to Bob, I will tell him.",  # hypothetical
        "Si je suis rattachée à Bob, tant mieux.",
        "I used to report to Bob.",
        "I no longer report to Bob.",
        "I don't report to Bob.",
        "Je ne suis plus rattachée à Bob.",
        "Avant, mon manager, Bob, validait tout.",
        "My previous manager, Bob, was strict.",
        "My boss's boss, Bob, is on the call.",
        "Le chef de mon chef, Bob, est là.",
        "Bob is the boss of Acme.",  # third party, not my boss
        "I work for Acme.",  # company, not a contact
        "I report to Carlos.",  # unknown person
        "Bob, my boss's boss, is on the call.",
    ],
)
def test_reports_to_negatives(text):
    assert [f for f in extract(text)[0] if f.kind == "reports_to"] == []


@pytest.mark.parametrize(
    "text",
    [
        "Moi je vais pousser ce dossier en interne.",
        "I'm going to champion this with the leadership team.",
        "I'm happy to defend it.",
        "Je vais défendre le renouvellement en interne.",
        "Je vais le défendre auprès de la direction.",
        "I'll back the proposal at the board.",
        "I will definitely sponsor the project.",
        "I'm happy to advocate for this internally.",
        "Je vais soutenir la proposition.",
    ],
)
def test_champion_generalised(text):
    assert [(f.kind, f.contact_id) for f in extract(text)[0]] == [("champion", ANA)]


@pytest.mark.parametrize(
    "text",
    [
        "If I'm going to champion this, I need data.",
        "I won't push this.",
        "I'll not defend it.",
        "Je ne vais pas défendre le projet.",
        "I'll support your decision.",
    ],
)
def test_champion_negatives(text):
    assert [f for f in extract(text)[0] if f.kind == "champion"] == []


@pytest.mark.parametrize(
    ("text", "who"),
    [
        ("Bob est plutôt réticent.", BOB),
        ("Zoé est plutôt réticente.", ZOE),
        ("Our CMO, Bob, is against it.", BOB),
        ("Zoe, our CFO, is quite skeptical.", ZOE),
        ("Notre CFO est contre, Zoé a refusé l'enveloppe.", ZOE),
        ("Bob a refusé la proposition.", BOB),
        ("Bob rejected the proposal last week.", BOB),
        ("Bob, notre DSI, est assez sceptique.", BOB),
    ],
)
def test_blocker_generalised(text, who):
    found = [f for f in extract(text)[0] if f.kind == "blocker"]
    assert found and found[0].contact_id == who


@pytest.mark.parametrize(
    "text",
    [
        "Je suis contre, franchement.",
        "Right now I'm against signing before the audit.",
        "I'm not convinced yet.",
        "Je ne suis pas convaincue.",
    ],
)
def test_blocker_first_person(text):
    assert [(f.kind, f.contact_id) for f in extract(text)[0]] == [("blocker", ANA)]


@pytest.mark.parametrize(
    "text",
    [
        "Bob is not against it.",
        "Bob n'est pas contre.",
        "Si Bob est contre, on verra.",
        "I'm not against it.",
        "Je ne suis pas contre.",
        "Je ne dis pas que je suis contre.",
        "Bob refused to come.",
        "Carlos est contre.",
    ],
)
def test_blocker_negatives(text):
    assert [f for f in extract(text)[0] if f.kind == "blocker"] == []


@pytest.mark.parametrize(
    ("text", "who"),
    [
        ("La décision finale revient à Bob.", BOB),
        ("Le dernier mot appartient à Zoé.", ZOE),
        ("Bob signe tous les contrats supérieurs à cinq mille euros.", BOB),
        ("Zoé, notre CEO, signe les contrats.", ZOE),
        ("The final call is with Bob.", BOB),
        ("The final decision rests with Zoe.", ZOE),
        ("The decision belongs to Bob.", BOB),
        ("Bob has the final say.", BOB),
        ("Zoe signs all the contracts above five thousand.", ZOE),
        ("Bob decides on the vendor.", BOB),
        ("C'est Bob qui a le dernier mot.", BOB),
        ("C'est Zoé qui arbitre.", ZOE),
        ("Zoé tranche les décisions budgétaires.", ZOE),
    ],
)
def test_decision_maker_generalised(text, who):
    found = [f for f in extract(text)[0] if f.kind == "decision_maker"]
    assert found and found[0].contact_id == who


@pytest.mark.parametrize(
    "text",
    ["C'est moi qui décide.", "C'est moi qui arbitre et qui signe.", "I make the final call here."],
)
def test_decision_maker_first_person(text):
    found = extract(text)[0]
    assert found and all(f.kind == "decision_maker" and f.contact_id == ANA for f in found)


@pytest.mark.parametrize(
    "text",
    [
        "Bob, as CEO, is around.",  # too vague
        "Bob doesn't sign contracts.",
        "Bob ne signe pas les contrats.",
        "If the final call is with Bob, fine.",
        "She signs the larger contracts.",  # pronoun, no named contact
        "Ce n'est pas moi qui décide.",
        "Carlos signe tous les contrats.",
    ],
)
def test_decision_maker_negatives(text):
    assert [f for f in extract(text)[0] if f.kind == "decision_maker"] == []
