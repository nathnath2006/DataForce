import uuid

import pytest
from sqlalchemy import delete, select

from app.db.models import Workspace
from app.db.session import SessionLocal, get_engine, make_session_factory, session_scope

pytestmark = pytest.mark.integration


def test_get_engine_is_cached_per_url(engine, test_database_url):
    assert get_engine(test_database_url) is engine
    assert get_engine(test_database_url) is get_engine(test_database_url)
    other = get_engine(test_database_url + "?application_name=other")
    assert other is not engine


def test_default_engine_is_the_test_database(engine, test_database_url):
    """conftest points DATABASE_URL at the test DB, so the no-argument paths cannot reach dev."""
    assert get_engine() is engine
    with SessionLocal() as session:
        assert session.get_bind() is engine


@pytest.fixture
def cleanup_slug(engine):
    slug = f"session-test-{uuid.uuid4().hex[:8]}"
    yield slug
    with engine.begin() as connection:  # these tests really commit: remove their rows
        connection.execute(delete(Workspace).where(Workspace.slug == slug))


def _make(slug):
    return Workspace(slug=slug, name="n")


def test_session_scope_commits_on_success(engine, cleanup_slug):
    with session_scope(make_session_factory(engine)) as session:
        session.add(_make(cleanup_slug))

    with session_scope() as other:  # default factory, a different session
        found = other.scalars(select(Workspace).where(Workspace.slug == cleanup_slug)).all()
    assert len(found) == 1


def test_session_scope_rolls_back_on_error(engine, cleanup_slug):
    factory = make_session_factory(engine)
    with pytest.raises(RuntimeError, match="boom"), session_scope(factory) as session:
        session.add(_make(cleanup_slug))
        session.flush()
        raise RuntimeError("boom")

    with session_scope() as other:
        found = other.scalars(select(Workspace).where(Workspace.slug == cleanup_slug)).all()
    assert found == []


def test_session_scope_closes_the_session(engine):
    with session_scope(make_session_factory(engine)) as session:
        session.execute(select(1))
    assert session.in_transaction() is False
