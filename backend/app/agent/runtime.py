"""Process-wide hook for the one tool that opens its own database sessions (`run_flow`).

The flow engine runs in a worker thread that reads through short-lived sessions of its own, as in
the API. By default they come from `SessionLocal`; tests (and the MCP server's tests) override the
factory with `set_session_factory`.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.db.session import SessionLocal

_factory: Callable[[], Session] | None = None


def set_session_factory(factory: Callable[[], Session] | None) -> None:
    global _factory
    _factory = factory


def get_session_factory() -> Callable[[], Session]:
    return _factory or SessionLocal
