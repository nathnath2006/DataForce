"""Choose the enrichment provider from settings (`enrichment_provider`)."""

from __future__ import annotations

from app.config import Settings
from app.domain.ports import EnrichmentProvider
from app.enrichment.errors import EnrichmentConfigError


def get_enrichment_provider(settings: Settings) -> EnrichmentProvider | None:
    """None when enrichment is off ("none"); a clear config error when a token is missing."""
    provider = settings.enrichment_provider
    if provider == "none":
        return None
    if provider == "fake":
        from app.enrichment.fake import FakeEnrichmentProvider

        return FakeEnrichmentProvider()
    if provider == "tamtam_mcp":
        token = settings.tamtam_mcp_token
        if token is None or len(token) == 0:
            raise EnrichmentConfigError(
                "ENRICHMENT_PROVIDER=tamtam_mcp requires TAMTAM_MCP_TOKEN (OAuth access token "
                "for https://api.tamtam.ai/mcp; see app/enrichment/tamtam_mcp.py)"
            )
        from app.enrichment.tamtam_mcp import TamTamMCPEnrichment

        return TamTamMCPEnrichment(settings)
    raise EnrichmentConfigError(f"Unknown ENRICHMENT_PROVIDER {provider!r}")
