"""People-contact enrichment (email / mobile) behind `app.domain.ports.EnrichmentProvider`.

    registry.get_enrichment_provider   "none" -> None | "fake" | "tamtam_mcp"
    tamtam_mcp.TamTamMCPEnrichment     TamTam MCP client; read its docstring for the assumptions

Paid lookups are refused unless the caller passes `allow_paid=True`.
"""
