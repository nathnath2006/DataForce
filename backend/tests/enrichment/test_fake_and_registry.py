"""FakeEnrichmentProvider and get_enrichment_provider."""

from __future__ import annotations

import pytest

from app.domain.ports import EnrichmentProvider
from app.domain.schemas import EnrichmentRequest
from app.enrichment.errors import EnrichmentConfigError, PaidLookupRefused
from app.enrichment.fake import FakeEnrichmentProvider
from app.enrichment.registry import get_enrichment_provider
from app.enrichment.tamtam_mcp import TamTamMCPEnrichment
from tests.enrichment.helpers import make_settings


def req(**kw):
    base = {"full_name": "Élodie Martin", "company_name": "Acme SAS", "want": ["email"]}
    base.update(kw)
    return EnrichmentRequest(**base)


async def test_fake_provider_has_the_same_paid_guard_as_the_real_one():
    fake = FakeEnrichmentProvider()
    for want in (["email"], ["mobile"], ["email", "mobile"]):
        with pytest.raises(PaidLookupRefused):
            await fake.enrich_contact(req(want=want), allow_paid=False)
    assert fake.calls == 0


async def test_fake_provider_is_deterministic_and_synthetic():
    fake = FakeEnrichmentProvider()
    a = await fake.enrich_contact(req(want=["email", "mobile"]), allow_paid=True)
    b = await fake.enrich_contact(req(want=["email", "mobile"]), allow_paid=True)
    assert a == b and fake.calls == 2
    assert a.email == "elodie.martin@acmesas.example"  # reserved TLD, accents folded
    assert a.mobile.startswith("+33 6 39 98")  # ARCEP fiction range
    assert (a.provider, a.credits_used, a.source) == ("fake", 11.0, "fake")


async def test_fake_provider_uses_the_company_domain_and_only_requested_fields():
    r = await FakeEnrichmentProvider().enrich_contact(
        req(company_domain="acme.fr", want=["email"]), allow_paid=True
    )
    assert r.email == "elodie.martin@acmefr.example" and r.mobile is None and r.credits_used == 1.0


def test_fake_provider_satisfies_the_port():
    assert isinstance(FakeEnrichmentProvider(), EnrichmentProvider)


def test_registry_none_means_no_provider():
    assert get_enrichment_provider(make_settings(enrichment_provider="none")) is None
    assert get_enrichment_provider(make_settings()) is None  # default is "none"


def test_registry_fake():
    assert isinstance(
        get_enrichment_provider(make_settings(enrichment_provider="fake")), FakeEnrichmentProvider
    )


def test_registry_tamtam_requires_a_token_and_names_it():
    with pytest.raises(EnrichmentConfigError, match="TAMTAM_MCP_TOKEN"):
        get_enrichment_provider(make_settings(enrichment_provider="tamtam_mcp"))
    with pytest.raises(EnrichmentConfigError, match="TAMTAM_MCP_TOKEN"):
        get_enrichment_provider(
            make_settings(enrichment_provider="tamtam_mcp", tamtam_mcp_token="")
        )


def test_registry_tamtam_with_token():
    s = make_settings(enrichment_provider="tamtam_mcp", tamtam_mcp_token="tok-secret")
    provider = get_enrichment_provider(s)
    assert isinstance(provider, TamTamMCPEnrichment) and provider.name == "tamtam_mcp"
    assert "tok-secret" not in repr(s) and "tok-secret" not in repr(vars(provider)["_settings"])
