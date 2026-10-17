"""Keep real tokens / provider choices from the developer's environment out of the tests."""

from __future__ import annotations

import pytest

ENV_VARS = ("TAMTAM_MCP_TOKEN", "ENRICHMENT_PROVIDER", "TAMTAM_MCP_URL")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
