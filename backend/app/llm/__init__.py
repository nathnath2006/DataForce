"""AI integrations: LLM + embedding providers behind the ports in `app.domain.ports`.

    registry.get_llm / get_embedder   choose gemini | anthropic | fake from settings
    untrusted.sanitize_text / wrap_sources   untrusted text -> safe <source> data blocks
    quotes.verify_quotes                      deterministic verbatim check of LLM quotes

Provider modules import their SDKs at module level, so import them through the registry.
"""
