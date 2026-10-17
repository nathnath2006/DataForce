"""LLM-layer errors.

Messages in these exceptions must never contain prompt text, page content or API keys: they are
persisted in `llm_call.error` and printed by the CLI. Put diagnostics in the exception chain
(`raise ... from exc`) if needed, never in the message.
"""

from __future__ import annotations

from pydantic import SecretStr


class LLMError(Exception):
    """A provider call failed (network, quota, refusal, timeout, invalid output...)."""


class LLMConfigError(LLMError):
    """The provider cannot be built from the current settings (missing key, unknown provider)."""


def require_secret(secret: SecretStr | None, env_var: str, *, needed_for: str) -> str:
    """Return the secret value, or raise a config error that names the env var to set.

    The only place (besides the provider clients) that calls `.get_secret_value()`.
    """
    if secret is None or len(secret) == 0:
        raise LLMConfigError(
            f"{env_var} is not set. It is required for {needed_for}. Put it in backend/.env "
            "(chmod 600) or the environment, or use the 'fake' provider for offline demos."
        )
    return secret.get_secret_value()
