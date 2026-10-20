from __future__ import annotations

import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_app_settings, get_db
from app.api.main import create_app
from app.config import Settings
from tests.api.conftest import TEST_SECRET_KEY, UI_ORIGIN

pytestmark = pytest.mark.integration


@pytest.fixture
def ws(client):
    client.post("/api/workspaces", json={"slug": "u1", "name": "U1"})
    client.post("/api/workspaces", json={"slug": "u2", "name": "U2"})
    return "/api/w/u1"


def up(client, ws, name, data, **form):
    return client.post(f"{ws}/files", files={"file": (name, data)}, data=form)


def test_upload_list_delete(client, ws):
    r = up(client, ws, "../x/people.csv", "a;b\n1;é\n2;y\n".encode("latin-1"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "people.csv" and body["n_rows"] == 2
    assert [c["name"] for c in body["columns"]] == ["a", "b"]
    assert "content" not in body
    assert len(client.get(f"{ws}/files").json()) == 1
    assert client.get("/api/w/u2/files").json() == []
    assert client.delete("/api/w/u2/files/" + body["id"]).status_code == 404
    assert client.delete(f"{ws}/files/{body['id']}").status_code == 204


def test_xlsx_and_refusals(client, ws):
    wb = openpyxl.Workbook()
    wb.active.append(["k", "v"])
    wb.active.append([1, 2.5])
    buf = io.BytesIO()
    wb.save(buf)
    r = up(client, ws, "d.xlsx", buf.getvalue())
    assert r.status_code == 201 and r.json()["n_rows"] == 1
    assert up(client, ws, "d.xlsx", buf.getvalue(), sheet="nope").status_code == 422
    assert up(client, ws, "d.xls", b"x").status_code == 422
    assert up(client, ws, "d.xlsx", b"not a zip").status_code == 422
    assert up(client, ws, "d.csv", b"").status_code == 422


def test_content_type_guards(client, ws):
    assert client.post(f"{ws}/files", json={"a": 1}).status_code == 415
    r = client.post(f"{ws}/accounts", files={"file": ("a.csv", b"a")})
    assert r.status_code == 415
    r = client.post(
        f"{ws}/files", files={"file": ("a.csv", b"a\n1")}, headers={"Origin": "http://evil.example"}
    )
    assert r.status_code == 403
    r = client.post(f"{ws}/files", files={"file": ("a.csv", b"a\n1")}, headers={"X-DataForce": ""})
    assert r.status_code == 403


def test_size_cap(app, client, session_factory):
    small = Settings(
        _env_file=None,
        environment="test",
        dataforce_secret_key=TEST_SECRET_KEY,
        upload_max_bytes=1024,
    )
    application = create_app(small)
    application.dependency_overrides[get_db] = app.dependency_overrides[get_db]
    application.dependency_overrides[get_app_settings] = lambda: small
    with TestClient(
        application, base_url=UI_ORIGIN, headers={"Origin": UI_ORIGIN, "X-DataForce": "1"}
    ) as c:
        c.cookies.update(client.cookies)  # signed in
        c.post("/api/workspaces", json={"slug": "u3", "name": "U3"})
        big = b"a\n" + b"1\n" * 200_000
        assert c.post("/api/w/u3/files", files={"file": ("a.csv", big)}).status_code == 413
        ok = c.post("/api/w/u3/files", files={"file": ("a.csv", b"a\n1\n")})
        assert ok.status_code == 201
