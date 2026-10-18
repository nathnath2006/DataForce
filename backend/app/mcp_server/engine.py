"""Database engine of the MCP process: a statement timeout on the connection itself (SR14-05).

`SET LOCAL statement_timeout` is lost at the first commit, and flow worker sessions never got it.
A libpq `options` startup parameter lives as long as the connection.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.session import connect_args_for, make_session_factory

STATEMENT_TIMEOUT_MS = 30_000


def make_engine(url: str | None = None) -> Engine:
    settings = get_settings()
    resolved = url or settings.database_url.get_secret_value()
    args = connect_args_for(resolved, settings)
    args["options"] = f"-c statement_timeout={STATEMENT_TIMEOUT_MS}"
    return create_engine(resolved, pool_pre_ping=True, hide_parameters=True, connect_args=args)


def make_factory(url: str | None = None) -> sessionmaker[Session]:
    return make_session_factory(make_engine(url))
