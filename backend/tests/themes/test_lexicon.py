from __future__ import annotations

import pytest

from app.themes.discover import discover
from app.themes.lexicon import BY_ID, CATALOG, best_known_sentence, match_known


def ids(text: str) -> set[str]:
    return {f.id for f in match_known([text]).found}


@pytest.mark.parametrize(
    ("text", "theme"),
    [
        ("Le tarif est trop élevé, c'est trop cher.", "price"),
        ("Could you offer a discount? The pricing is steep.", "price"),
        ("Une réduction de volume ?", "price"),
        ("Votre concurrent est moins cher.", "competitor"),
        ("We compared to a similar offer from another vendor.", "competitor"),
        ("Où se fait l'hébergement, et le RGPD ?", "security"),
        ("Do you have a SOC 2 report and ISO 27001?", "security"),
        ("Il nous faut une intégration avec Salesforce via l'API.", "integration"),
        ("Is there a webhook for the CRM sync?", "integration"),
        ("Il y a un gel des budgets, pas avant le prochain trimestre.", "timing"),
        ("Everything is postponed until next quarter.", "timing"),
        ("Pouvez-vous relire la clause du contrat ?", "legal"),
        ("We need training and an onboarding plan.", "onboarding"),
        ("What is the SLA and the response time of support?", "support"),
    ],
)
def test_fr_en_accents(text, theme):
    assert theme in ids(text)


def test_catalog_shape():
    assert {d.id for d in CATALOG} == {
        "price", "competitor", "security", "integration", "timing", "legal", "onboarding", "support"
    }  # fmt: skip
    assert BY_ID["price"].kind == "objection" and BY_ID["timing"].kind == "timing"


def test_word_boundaries():
    # Decision: no match inside longer words ("priceless", "pricey", "important", "supporting").
    assert "price" not in ids("A priceless moment, a pricey coffee.")
    assert "integration" not in ids("It is important and impressive.")
    assert "support" not in ids("Supportive colleagues.")


def test_budget_freeze_is_timing_not_price():
    assert ids("Il y a un gel des budgets chez nous.") == {"timing"}
    assert ids("We have a budget freeze.") == {"timing"}
    assert "price" in ids("Notre budget est limité.")


def test_reporting_line_is_not_timing():
    assert "timing" not in ids("Je reporte à Marie Dupont.")
    assert "timing" not in ids("Send me the report.")


def test_multi_theme_sentence_and_chunk():
    res = match_known(["Le prix et la sécurité RGPD posent problème. Merci."])
    assert {f.id for f in res.found} == {"price", "security"}
    res = match_known(["Le prix est cher.\nParlons du RGPD."])
    assert {f.id for f in res.found} == {"price", "security"}


def test_unmatched_theme_not_returned_and_excerpts_exact():
    texts = [f"Doc {i}: prix trop cher et remise. Autre phrase. Le tarif aussi." for i in range(5)]
    res = match_known(texts, doc_ids=list("aabbc"))
    assert [f.id for f in res.found] == ["price"]
    f = res.found[0]
    assert len(f.excerpts) == 3
    assert all(any(s in t for t in texts) for _, s in f.excerpts)
    assert len({texts_i for texts_i, _ in f.excerpts}) == 3
    assert f.top_terms[0] in {"prix", "cher", "remise", "tarif"}
    assert best_known_sentence("Price", "Bonjour. Le prix et la remise sont chers.").endswith(
        "chers."
    )


def competitor_corpus(person="Marie"):
    texts = []
    for i in range(4):
        texts.append(f"Nous regardons aussi Vendara pour comparer. Merci {person}.")
        texts.append(f"On a testé Vendara la semaine dernière à Lyon. Bonjour {person}.")
    return texts, [i // 2 for i in range(8)]


def test_competitor_name_detected():
    texts, docs = competitor_corpus()
    res = match_known(texts, doc_ids=docs)
    assert res.competitor_names == ["Vendara"]
    comp = next(f for f in res.found if f.id == "competitor")
    assert "Vendara" in comp.description
    # a sentence naming it matches the competitor theme even without a cue word
    res2 = match_known(["Vendara propose une interface."] + texts, doc_ids=[99] + docs)
    assert any(ci == 0 for ci, _ in next(f for f in res2.found if f.id == "competitor").members)


def test_person_names_never_competitors():
    texts = [f"Nous avons comparé avec Durand, et testé Durand. Merci {i}." for i in range(5)]
    assert match_known(texts, ["Paul Durand"], doc_ids=list(range(5))).competitor_names == []
    assert match_known(texts, doc_ids=list(range(5))).competitor_names == ["Durand"]


def test_name_needs_three_meetings_and_no_lowercase_use():
    texts = ["On a testé Vendara ici."] * 2
    assert match_known(texts, doc_ids=[1, 2]).competitor_names == []
    texts = ["On a testé Bureau ici."] * 3 + ["Le bureau est grand."]
    assert match_known(texts, doc_ids=[1, 2, 3, 4]).competitor_names == []


def test_deterministic():
    texts, docs = competitor_corpus()
    a, b = match_known(texts, doc_ids=docs), match_known(texts, doc_ids=docs)
    assert a == b


def test_other_topics_only_on_unmatched_sentences():
    texts = [
        f"Le prix est cher. {'violon mélodie concert' if i % 2 else 'jardin orchidée serre'} "
        f"numéro{i % 3}."
        for i in range(24)
    ]
    docs = list(range(24))
    known = match_known(texts, doc_ids=docs)
    assert [f.id for f in known.found] == ["price"]
    disc = discover(texts, 2, doc_ids=docs, skip=known.matched)
    terms = {t for th in disc.themes for t in th.top_terms}
    assert terms and not terms & {"prix", "price", "cher", "expensive"}
    assert {"violon", "jardin"} & terms


def test_filler_topics_dropped():
    texts = [
        f"interessant surtout clair vraiment {w}" for w in "alpha beta gamma delta".split()
    ] * 3
    from app.themes.discover import ThemeError

    try:
        res = discover(texts, 3, doc_ids=list(range(len(texts))))
    except ThemeError:
        return
    assert all("interessant" not in th.top_terms for th in res.themes)


def _themes(text):
    from app.themes.lexicon import match_known

    return {f.id for f in match_known([text]).found}


def test_context_rules_remove_false_positives():
    assert "integration" not in _themes("Une nouvelle intégration de stagiaires aura lieu.")
    assert "integration" not in _themes("L'intégration des nouveaux collaborateurs est lundi.")
    assert "support" not in _themes("Le support de présentation est joint.")
    assert "support" not in _themes("Le support de cours est joint.")
    assert "support" not in _themes("I support your decision completely.")
    assert "price" not in _themes("Le coût de la vie à Paris est dingue.")
    assert "price" not in _themes("Budget meeting at three.")
    assert "legal" not in _themes("She has a legal background.")
    # the general terms still match
    assert "integration" in _themes("We need an integration with Salesforce.")
    assert "support" in _themes("What support do you offer?")
    assert "price" in _themes("The price is too high.")
