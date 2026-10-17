"""Serving the built SPA: fallback, JSON API 404s, path traversal."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from tests.api.conftest import TEST_SECRET_KEY

pytestmark = pytest.mark.integration

INDEX = "<!doctype html><title>spa</title>"


@pytest.fixture
def api_settings(tmp_path) -> Settings:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX)
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("TOP SECRET")
    return Settings(
        _env_file=None, environment="test", dataforce_secret_key=TEST_SECRET_KEY, ui_dist_dir=dist
    )


def test_index_and_assets(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200 and "spa" in r.text
    assert r.headers["x-frame-options"] == "DENY"
    js = client.get("/assets/app.js")
    assert js.status_code == 200 and js.text == "console.log(1)"


def test_spa_fallback_for_client_routes(client: TestClient):
    for path in ("/w/demo/accounts", "/w/demo/accounts/123", "/settings"):
        r = client.get(path)
        assert r.status_code == 200 and "spa" in r.text, path


def test_missing_file_is_404_not_index(client: TestClient):
    assert client.get("/assets/missing.js").status_code == 404


def test_api_stays_json(client: TestClient):
    r = client.get("/api/unknown")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["error"]["code"] == "not_found"
    assert client.get("/api/health").json()["ok"] is True
    assert client.get("/api").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/../secret.txt",
        "/%2e%2e/secret.txt",
        "/..%2fsecret.txt",
        "/assets/../../secret.txt",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/%00",
    ],
)
def test_traversal_refused(client: TestClient, path: str):
    r = client.get(path)
    assert "TOP SECRET" not in r.text
    assert r.status_code in (200, 400, 404)  # index fallback or an error, never the file


def test_no_dist_means_api_only(app, tmp_path):
    from app.api.main import create_app

    settings = Settings(_env_file=None, environment="test", ui_dist_dir=tmp_path / "none")
    bare = TestClient(create_app(settings), base_url="http://127.0.0.1:8800")
    assert bare.get("/").status_code == 404
    assert bare.get("/api/health").status_code == 200
