"""Autouse fixture: keep the developer's real keys / provider choices out of the tests."""

from __future__ import annotations

import pytest

from tests.llm.helpers import ENV_VARS


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
