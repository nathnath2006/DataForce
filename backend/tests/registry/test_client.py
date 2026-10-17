"""Registry client: parsing and the HTTP guards. respx only: the real registry is never called."""

from __future__ import annotations

import copy
import time

import httpx
import pytest
import respx

from app.config import Settings
from app.enrichment.errors import EnrichmentError
from app.registry import client as reg

SAMPLE = {
    "siren": "791012081",
    "nom_complet": "DATAIKU",
    "nom_raison_sociale": "DATAIKU",
    "siege": {
        "adresse": "201-203 201 RUE DE BERCY 75012 PARIS",
        "code_postal": "75012",
        "libelle_commune": "PARIS",
        "activite_principale": "58.29C",
        "statut_diffusion_etablissement": "O",
    },
    "activite_principale": "58.29C",
    "categorie_entreprise": "ETI",
    "nature_juridique": "5710",
    "tranche_effectif_salarie": "32",
    "etat_administratif": "A",
    "statut_diffusion": "O",
    "date_creation": "2013-01-26",
    "complements": {"est_entrepreneur_individuel": False},
    "dirigeants": [{"nom": "SECRET-MANAGER", "prenoms": "X"}],
    "finances": {"2023": {"ca": 123456789}},
}
URL = "https://registry.test"


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    monkeypatch.setattr(reg, "_min_interval_s", 0.0)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, environment="test", registry_url=URL)


def test_parse_sample():
    c = reg.parse_record(SAMPLE)
    assert c is not None
    assert (c.siren, c.name, c.city, c.postal_code) == ("791012081", "DATAIKU", "PARIS", "75012")
    assert c.address_line == "201-203 201 RUE DE BERCY 75012 PARIS"
    assert (c.naf_code, c.legal_category, c.size_bracket, c.category) == (
        "58.29C",
        "5710",
        "32",
        "ETI",
    )
    assert c.created_on.isoformat() == "2013-01-26"
    assert c.active and not c.sole_trader


def test_dirigeants_and_finances_never_parsed():
    c = reg.parse_record(SAMPLE)
    dumped = c.model_dump_json()
    assert "SECRET-MANAGER" not in dumped and "123456789" not in dumped
    assert not any("dirig" in f or "financ" in f for f in reg.RegistryCompany.model_fields)

    class Trap(dict):
        def __getitem__(self, k):
            assert k not in ("dirigeants", "finances")
            return super().__getitem__(k)

        def get(self, k, default=None):
            assert k not in ("dirigeants", "finances"), k
            return super().get(k, default)

    assert reg.parse_record(Trap(SAMPLE)) is not None


@pytest.mark.parametrize("where", ["top", "siege"])
def test_protected_address_dropped(where):
    rec = copy.deepcopy(SAMPLE)
    if where == "top":
        rec["statut_diffusion"] = "P"
    else:
        rec["siege"]["statut_diffusion_etablissement"] = "N"
    c = reg.parse_record(rec)
    assert c.address_line is None and c.postal_code is None and c.city is None
    assert c.name == "DATAIKU" and c.naf_code == "58.29C"  # business data is kept


def test_missing_status_is_protected():
    rec = copy.deepcopy(SAMPLE)
    del rec["statut_diffusion"]
    assert reg.parse_record(rec).address_line is None


def test_sole_trader_and_inactive():
    rec = copy.deepcopy(SAMPLE)
    rec["complements"] = {"est_entrepreneur_individuel": True}
    rec["etat_administratif"] = "C"
    rec["nom_raison_sociale"] = None
    rec["nom_complet"] = "JEAN DUPONT"
    c = reg.parse_record(rec)
    assert c.sole_trader and not c.active and c.name == "JEAN DUPONT"


@pytest.mark.parametrize("bad", [None, [], {"siren": "12"}, {"siren": "791012081"}])
def test_bad_records_skipped(bad):
    assert reg.parse_record(bad) is None


@respx.mock
async def test_search_ok_and_params(settings):
    route = respx.get(f"{URL}/search").mock(
        return_value=httpx.Response(200, json={"results": [SAMPLE, {"siren": "x"}]})
    )
    found = await reg.search(settings, " dataiku ")
    assert [c.siren for c in found] == ["791012081"]
    sent = route.calls.last.request.url.params
    assert sent["q"] == "dataiku" and sent["page"] == "1"


@respx.mock
async def test_empty_query_makes_no_call(settings):
    route = respx.get(f"{URL}/search")
    assert await reg.search(settings, "  ") == []
    assert not route.called


async def test_query_too_long(settings):
    with pytest.raises(EnrichmentError, match="longer"):
        await reg.search(settings, "a" * 101)


async def test_non_https_refused(settings):
    plain = settings.model_copy(update={"registry_url": "http://registry.test"})
    with respx.mock(assert_all_called=False) as m:
        route = m.get("http://registry.test/search")
        with pytest.raises(EnrichmentError, match="https"):
            await reg.search(plain, "x")
        assert not route.called


@respx.mock
async def test_size_cap(settings):
    big = b'{"results": []}' + b" " * (reg.MAX_RESPONSE_BYTES + 10)
    respx.get(f"{URL}/search").mock(return_value=httpx.Response(200, content=big))
    with pytest.raises(EnrichmentError, match="too large"):
        await reg.search(settings, "x")


@respx.mock
async def test_timeout(settings):
    respx.get(f"{URL}/search").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(EnrichmentError, match="could not be reached"):
        await reg.search(settings, "x")


@respx.mock
async def test_redirect_refused(settings):
    respx.get(f"{URL}/search").mock(
        return_value=httpx.Response(302, headers={"location": "https://evil.test/"})
    )
    with pytest.raises(EnrichmentError, match="redirect"):
        await reg.search(settings, "x")


@respx.mock
@pytest.mark.parametrize(
    ("status", "content"),
    [(500, b"{}"), (429, b"{}"), (200, b"not json"), (200, b'{"results": 3}')],
)
async def test_bad_answers(settings, status, content):
    respx.get(f"{URL}/search").mock(return_value=httpx.Response(status, content=content))
    with pytest.raises(EnrichmentError):
        await reg.search(settings, "x")


@respx.mock
async def test_fetch_by_siren(settings):
    other = copy.deepcopy(SAMPLE) | {"siren": "123456789"}
    respx.get(f"{URL}/search").mock(
        return_value=httpx.Response(200, json={"results": [other, SAMPLE]})
    )
    assert (await reg.fetch_by_siren(settings, "791012081")).name == "DATAIKU"
    assert await reg.fetch_by_siren(settings, "999999999") is None
    with pytest.raises(EnrichmentError):
        await reg.fetch_by_siren(settings, "12")


async def test_rate_limit_spaces_requests(monkeypatch):
    monkeypatch.setattr(reg, "_min_interval_s", 0.2)
    monkeypatch.setattr(reg, "_next_slot", 0.0)
    start = time.monotonic()
    for _ in range(3):
        await reg._throttle()
    assert time.monotonic() - start >= 0.38
