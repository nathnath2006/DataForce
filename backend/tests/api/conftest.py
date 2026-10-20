"""Fixtures for API tests (contract: owned by the tech lead).

`client` talks to the real app (create_app) whose DB sessions share the test connection: what
a route commits is a savepoint, rolled back when the test ends. It sends the headers a real
browser on the UI origin sends for state-changing requests (Origin + X-DataForce).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_app_settings, get_db, get_session_factory
from app.api.main import create_app
from app.auth import ratelimit
from app.config import Settings
from tests.api.auth_helpers import login_as, make_member_in, sign_in_superadmin  # noqa: F401

# A fixed test-only Fernet key (urlsafe base64 of 32 bytes). Never used outside tests.
TEST_SECRET_KEY = "ZGF0YWZvcmNlLXRlc3Qta2V5LW5vdC1mb3ItcHJvZCE="
UI_ORIGIN = "http://127.0.0.1:8800"


@pytest.fixture
def api_settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        dataforce_secret_key=TEST_SECRET_KEY,
        ui_dist_dir=tmp_path / "no-dist",
    )


@pytest.fixture
def app(api_settings: Settings, session_factory: sessionmaker[Session]) -> FastAPI:
    application = create_app(api_settings)

    def _db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.rollback()
            session.close()

    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[get_app_settings] = lambda: api_settings
    application.dependency_overrides[get_session_factory] = lambda: session_factory
    return application


@pytest.fixture
def anon_client(app: FastAPI) -> Iterator[TestClient]:
    """A browser that is not signed in."""
    ratelimit.reset()
    with TestClient(
        app, base_url=UI_ORIGIN, headers={"Origin": UI_ORIGIN, "X-DataForce": "1"}
    ) as test_client:
        yield test_client


@pytest.fixture
def client(anon_client: TestClient, session_factory: sessionmaker[Session]) -> TestClient:
    """Signed in as a superadmin created for the test (sees every workspace). Other developers:
    to act as a rep use `make_member` + `login_as` (tests/api/auth_helpers.py)."""
    sign_in_superadmin(anon_client, session_factory)
    return anon_client


@pytest.fixture
def make_member(session_factory: sessionmaker[Session]):
    """`make_member(ws_slug, role="rep", see_all=False, delete_own=False, app_user_id=None)`
    -> Member(email, password); then `login_as(client, m.email, m.password)`."""
    return lambda *a, **kw: make_member_in(session_factory, *a, **kw)
