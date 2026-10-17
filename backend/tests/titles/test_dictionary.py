"""Dictionary, normaliser and accuracy on the demo's noisy titles."""

from __future__ import annotations

import numpy as np
import pytest

from app.demo import names as N
from app.demo.generator import _noisy_title
from app.titles.classify import classify_title
from app.titles.normalize import normalize_title

EXPECTED = {
    "ceo": ("executive", {"c_level"}),
    "vp_sales": ("sales", {"vp", "head"}),
    "cmo": ("marketing", {"c_level", "head"}),
    "cfo": ("finance", {"c_level", "head"}),
    "head_sales": ("sales", {"head", "manager"}),
    "ae": ("sales", {"individual"}),
    "sdr": ("sales", {"individual"}),
    "marketing": ("marketing", {"manager", "individual"}),
    "ops": ("operations", {"manager"}),
}
VARIANTS = [(r, t) for r, ts in N.ROLE_TITLES.items() for t in ts]


@pytest.mark.parametrize(("role", "title"), VARIANTS)
def test_every_role_variant(role, title):
    fn, sen = EXPECTED[role]
    c = classify_title(title)
    assert c.function.value == fn, (title, c)
    assert c.seniority.value in sen, (title, c)
    assert c.flag is None


def test_accuracy_on_noisy_titles(capsys):
    f = s = n = 0
    for seed in range(40):
        rng = np.random.default_rng(seed)
        for _ in range(50):
            role = list(N.ROLE_TITLES)[int(rng.integers(len(N.ROLE_TITLES)))]
            t = _noisy_title(rng, role)
            if t is None:
                continue
            c = classify_title(t)
            n += 1
            f += c.function.value == EXPECTED[role][0]
            s += c.seniority.value in EXPECTED[role][1]
    print(f"ACCURACY n={n} function={f / n:.4f} seniority={s / n:.4f}")
    assert n > 1500
    assert f / n >= 0.90
    assert s / n >= 0.85


def test_typos_and_glue():
    assert normalize_title("accoun texecutive") == "account executive"
    assert classify_title("Accoun texecutive").function.value == "sales"
    assert normalize_title("Directuer commercial") == "directeur commercial"
    assert classify_title("Direteur marketnig").function.value == "marketing"
    assert normalize_title("Dir. d'Affaires") == "directeur d affaires"


def test_specificity_and_ambiguity():
    c = classify_title("Chief Marketing Officer")
    assert (c.function.value, c.seniority.value) == ("marketing", "c_level")
    assert classify_title("Vice President Sales").seniority.value == "vp"
    c = classify_title("Directeur commercial et marketing")
    assert c.function.value == "unknown"
    assert c.flag == "ambiguous function: sales, marketing"


def test_missing_and_unknown():
    c = classify_title(None)
    assert (c.function.value, c.seniority.value, c.flag) == ("unknown", "unknown", "no title")
    c = classify_title("Astronaute")
    assert c.source == "none" and c.flag == "unknown title" and not c.matched
