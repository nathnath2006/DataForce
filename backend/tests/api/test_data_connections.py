from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from app.api.deps import get_app_settings
from app.config import get_settings

pytestmark = pytest.mark.integration

PW = "unit-test-pw-123"


@pytest.fixture(autouse=True)
def _allow_test_db(monkeypatch):
    """The test database is also DATABASE_URL here; SR14-02 tests turn the refusal back on."""
    from app.flows.sources import postgres

    monkeypatch.setattr(postgres, "_app_database", lambda: None)


@pytest.fixture
def ws(client):
    client.post("/api/workspaces", json={"slug": "c1", "name": "C1"})
    client.post("/api/workspaces", json={"slug": "c2", "name": "C2"})
    return "/api/w/c1"


def body(**kw):
    url = make_url(get_settings().test_database_url.get_secret_value())
    base = {
        "name": "local",
        "host": "127.0.0.1",
        "port": url.port,
        "database": url.database,
        "username": url.username,
        "password": url.password,
        "sslmode": "disable",
    }
    return {**base, **kw}


def test_password_never_returned(client, ws):
    r = client.post(f"{ws}/connections", json=body(password=PW))
    assert r.status_code == 201
    assert PW not in r.text and r.json()["has_password"] is True and "password" not in r.json()
    cid = r.json()["id"]
    assert PW not in client.get(f"{ws}/connections").text
    # a real stored password works; a bad one is reported without being echoed
    t = client.post(f"{ws}/connections/{cid}/test").json()
    assert t["last_test_ok"] is False and PW not in str(t) and t["last_test_at"]
    # PATCH with an empty password keeps the stored one; a new one replaces it
    p = client.patch(f"{ws}/connections/{cid}", json={"password": "", "name": "renamed"})
    assert p.json()["name"] == "renamed" and p.json()["has_password"] is True
    assert (
        client.patch(f"{ws}/connections/{cid}", json={"password": body()["password"]}).status_code
        == 200
    )
    ok = client.post(f"{ws}/connections/{cid}/test").json()
    assert ok["last_test_ok"] is True and ok["last_error"] is None
    tables = client.get(f"{ws}/connections/{cid}/tables").json()
    assert any(t["schema"] == "public" for t in tables)
    assert client.get(f"/api/w/c2/connections/{cid}/tables").status_code == 404


def test_tls_and_validation(client, ws):
    r = client.post(f"{ws}/connections", json=body(host="db.example.com", sslmode="prefer"))
    assert r.status_code == 422
    r = client.post(f"{ws}/connections", json=body(host="db.example.com", sslmode="require"))
    assert r.status_code == 201
    cid = r.json()["id"]
    assert client.patch(f"{ws}/connections/{cid}", json={"sslmode": "disable"}).status_code == 422
    assert client.post(f"{ws}/connections", json=body(host="a,b")).status_code == 422
    assert (
        client.post(
            f"{ws}/connections", json=body(name="local", host="db.example.com", sslmode="require")
        ).status_code
        == 409
    )
    assert client.delete(f"{ws}/connections/{cid}").status_code == 204


def test_loader_reads_postgres_through_connection(client, ws, app, session_factory):
    import uuid

    from app.api.routes.flows import get_loader_session_factory
    from app.flows.schemas import PostgresSource
    from app.flows.sources.loader import DbSourceLoader

    app.dependency_overrides[get_loader_session_factory] = lambda: session_factory
    cid = client.post(f"{ws}/connections", json=body()).json()["id"]
    from sqlalchemy import select

    from app.db.models import Workspace

    s = session_factory()
    ws_id = s.scalar(select(Workspace.id).where(Workspace.slug == "c1"))
    loader = DbSourceLoader(session_factory, ws_id, app.dependency_overrides[get_app_settings]())
    df = loader.load(PostgresSource(connection_id=cid, query="SELECT 1 AS one"), 10)
    assert list(df["one"]) == [1]
    from app.flows.ports import SourceError

    with pytest.raises(SourceError):
        loader.load(PostgresSource(connection_id=uuid.uuid4(), query="SELECT 1"), 10)


def test_moving_the_server_requires_the_password_again(client, ws, monkeypatch):
    from app.flows.sources import postgres

    cid = client.post(f"{ws}/connections", json=body()).json()["id"]
    sent = []
    monkeypatch.setattr(postgres, "check_connection", lambda t: sent.append(t))
    for change in ({"port": 1}, {"host": "localhost"}, {"database": "other"}, {"username": "x"}):
        r = client.patch(f"{ws}/connections/{cid}", json=change)
        assert r.status_code == 422, change
        assert "re-enter the password" in r.json()["error"]["message"]
    client.post(f"{ws}/connections/{cid}/test")
    assert [t.host for t in sent] == ["127.0.0.1"]  # nothing moved: the old password stays here
    # a new password in the same request is accepted, and a harmless rename needs none
    assert (
        client.patch(f"{ws}/connections/{cid}", json={"port": 1, "password": "new"}).status_code
        == 200
    )
    assert client.patch(f"{ws}/connections/{cid}", json={"name": "renamed"}).status_code == 200
    client.post(f"{ws}/connections/{cid}/test")
    assert sent[-1].password == "new" and sent[-1].port == 1


def test_application_database_refused_on_save_test_and_load(
    client, ws, monkeypatch, session_factory, app
):
    """SR14-02: a connection to the DataForce database is refused when saved, when tested and by
    the source loader (for rows saved before the rule)."""
    import uuid

    from app.db.models import Workspace
    from app.flows.ports import SourceError
    from app.flows.schemas import PostgresSource
    from app.flows.sources import postgres
    from app.flows.sources.loader import DbSourceLoader

    ok = client.post(f"{ws}/connections", json=body()).json()
    assert "id" in ok  # allowed while the guard is off
    monkeypatch.undo()  # guard on: DATABASE_URL is the test database
    for host in ("127.0.0.1", "localhost", "::1"):
        r = client.post(f"{ws}/connections", json=body(name=f"x{host}", host=host))
        assert r.status_code == 422 or r.status_code == 400, r.text
        assert "application database" in r.text
    other = client.post(f"{ws}/connections", json=body(name="o", database="elsewhere"))
    assert other.status_code in (200, 201)
    r = client.patch(
        f"{ws}/connections/{other.json()['id']}", json={"database": body()["database"]}
    )
    assert r.status_code in (400, 422) and "application database" in r.text
    t = client.post(f"{ws}/connections/{ok['id']}/test").json()
    assert t["last_test_ok"] is False and "application database" in t["last_error"]
    with session_factory() as s:
        ws_id = s.query(Workspace).filter_by(slug="c1").one().id
    loader = DbSourceLoader(session_factory, ws_id, get_settings())
    src = PostgresSource(connection_id=uuid.UUID(ok["id"]), table="workspace")
    with pytest.raises(SourceError, match="application database"):
        loader.load(src, 10)
    assert not postgres.targets_app_database("127.0.0.1", 1, "x")
