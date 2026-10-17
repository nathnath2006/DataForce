"""The request guards: Host, Origin + X-DataForce, content type, body size, headers."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

UI = "http://127.0.0.1:8800"
JSON = {"content-type": "application/json"}


def test_security_headers_everywhere(client: TestClient):
    for path in ("/api/health", "/api/nope", "/nothing-here"):
        r = client.get(path)
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"
        assert r.headers["x-frame-options"] == "DENY"
        csp = r.headers["content-security-policy"]
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert client.get("/api/health").headers["cache-control"] == "no-store"
    assert client.get("/api/nope").headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "host", ["127.0.0.1:8800", "localhost:8800", "[::1]:8800", "127.0.0.1:5173", "localhost:5173"]
)
def test_allowed_hosts(client: TestClient, host: str):
    assert client.get("/api/health", headers={"host": host}).status_code == 200


@pytest.mark.parametrize(
    "host",
    ["evil.example", "evil.example:8800", "127.0.0.1", "127.0.0.1:9999", "127.0.0.1.evil.io:8800"],
)
def test_bad_host_is_400(client: TestClient, host: str):
    r = client.get("/api/health", headers={"host": host})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_input"
    assert r.headers["x-frame-options"] == "DENY"  # headers also on guard answers


def test_unsafe_methods_need_origin_and_header(client: TestClient):
    body = {"slug": "guarded", "name": "G"}
    ok = client.post("/api/workspaces", json=body)
    assert ok.status_code == 201
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        bare = TestClient(client.app, base_url=UI)
        r = bare.request(method, "/api/workspaces", json=body)
        assert r.status_code == 403, method
        assert r.json()["error"]["code"] == "forbidden"
    # origin present but foreign, or header missing / wrong
    for headers in (
        {"Origin": "https://evil.example", "X-DataForce": "1"},
        {"Origin": UI},
        {"Origin": UI, "X-DataForce": "0"},
        {"X-DataForce": "1"},
        {"Origin": "null", "X-DataForce": "1"},
    ):
        bare = TestClient(client.app, base_url=UI)
        r = bare.post("/api/workspaces", json={"slug": "other", "name": "O"}, headers=headers)
        assert r.status_code == 403, headers
    assert client.get("/api/workspaces").status_code == 200  # GET needs neither


def test_vite_origin_is_allowed(client: TestClient):
    r = client.post(
        "/api/workspaces",
        json={"slug": "vite", "name": "V"},
        headers={"Origin": "http://localhost:5173", "host": "localhost:5173"},
    )
    assert r.status_code == 201


def test_no_cors_headers(client: TestClient):
    r = client.options(
        "/api/workspaces",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in r.headers


def test_body_must_be_json(client: TestClient):
    r = client.post(
        "/api/workspaces", content=b"slug=x&name=y", headers={"content-type": "text/plain"}
    )
    assert r.status_code == 415
    r = client.post(
        "/api/workspaces",
        content=b"slug=x&name=y",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 415
    r = client.post(
        "/api/workspaces",
        content=b"{}",
        headers={"content-type": "application/json; charset=utf-8"},
    )
    assert r.status_code == 422  # reached the route: JSON accepted


def test_oversized_body_is_413(client: TestClient):
    big = b'{"slug": "x", "name": "' + b"a" * (300 * 1024) + b'"}'
    r = client.post("/api/workspaces", content=big, headers=JSON)
    assert r.status_code == 413
    r = client.post("/api/workspaces", content=iter([b"a" * 200_000, b"b" * 200_000]), headers=JSON)
    assert r.status_code == 413  # chunked: no Content-Length to trust
    ok = b'{"slug": "okbody", "name": "N"}' + b" " * (200 * 1024)  # large but under the cap
    assert client.post("/api/workspaces", content=ok, headers=JSON).status_code == 201


def test_post_without_body_needs_no_content_type(client: TestClient):
    # POST scan has no body; the guard must not demand a content type for it
    client.post("/api/workspaces", json={"slug": "nobody", "name": "N"})
    assert client.post("/api/w/nobody/stats/scan").status_code == 200
