"""Hosted mode (docs/HOSTED-MODE-CONTRACT.md): PUBLIC_ORIGIN is the one switch."""

from __future__ import annotations

import pytest
import typer
from pydantic import ValidationError

from app.api.security import ForwardedClientMiddleware, forwarded_client
from app.auth.access import empty_password_allowed, is_loopback
from app.cli import serve as serve_cli
from app.config import Settings, effective_origins, is_hosted
from app.connectors import oauth
from app.connectors.mailbox import google, microsoft
from tests.api.conftest import TEST_SECRET_KEY

ORIGIN = "https://dataforce-abc123-ew.a.run.app"
HOSTED = {
    "environment": "test",
    "dataforce_secret_key": TEST_SECRET_KEY,
    "public_origin": ORIGIN,
}


def make(**kw: object) -> Settings:
    return Settings(_env_file=None, **{"environment": "test", **kw})  # type: ignore[arg-type]


# --- settings (unit) -------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad",
    [
        "http://dataforce.example",
        "http://127.0.0.1:8800",
        "https://x.example/app",
        "https://x.example?a=1",
        "https://user@x.example",
        "dataforce.example",
    ],
)
def test_public_origin_refused(bad: str):
    with pytest.raises(ValidationError):
        make(public_origin=bad)


def test_public_origin_normalised_and_local_by_default():
    assert make().public_origin == "" and not is_hosted(make())
    s = make(public_origin="https://DataForce.Example/")
    assert s.public_origin == "https://dataforce.example" and is_hosted(s)


def test_effective_origins_replaced_when_hosted():
    assert effective_origins(make()) == make().ui_allowed_origins
    assert effective_origins(make(public_origin=ORIGIN)) == [ORIGIN]


def test_callback_urls_use_public_origin():
    s = make(public_origin=ORIGIN)
    assert oauth.redirect_uri_for(s, "127.0.0.1:8800") == f"{ORIGIN}/api/connectors/tamtam/callback"
    assert google.redirect_uri(s) == f"{ORIGIN}/api/mailbox/callback"
    assert microsoft.redirect_uri(s) == f"{ORIGIN}/api/mailbox/callback"


def test_no_empty_password_when_hosted():
    s = make(public_origin=ORIGIN, ui_host="127.0.0.1")
    assert is_loopback(make()) and not is_loopback(s)
    assert empty_password_allowed(None, s, None) is False  # type: ignore[arg-type]


# --- serve refusals (unit, never binds a port) -----------------------------------------------
REMOTE_DB = "postgresql+psycopg://app:Zq7-pw-Zq7-pw@db.example.supabase.co:5432/postgres"
GOOD = {
    "public_origin": ORIGIN,
    "dataforce_secret_key": TEST_SECRET_KEY,
    "environment": "demo",
    "database_url": f"{REMOTE_DB}?sslmode=require",
}


def _run_serve(monkeypatch, **kw: object) -> int:
    values = {**GOOD, **kw}
    values = {k: v for k, v in values.items() if v is not None}
    monkeypatch.setattr(serve_cli, "get_settings", lambda: Settings(_env_file=None, **values))  # type: ignore[arg-type]
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("must not start"))
    monkeypatch.setattr(serve_cli.runs, "reap_stale_runs_at_startup", lambda: None)
    try:
        serve_cli.serve()
    except typer.Exit as exc:
        return exc.exit_code
    return 0


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"public_origin": ""}, "PUBLIC_ORIGIN"),
        ({"dataforce_secret_key": None}, "DATAFORCE_SECRET_KEY"),
        (
            {
                "environment": "dev",
                "database_url": "postgresql+psycopg://dataforce:dataforce@localhost:5433/dataforce",
            },
            "ENVIRONMENT=dev",
        ),
        ({"environment": "test"}, "ENVIRONMENT=test"),
    ],
)
def test_serve_refuses(monkeypatch, capsys, override, message):
    assert _run_serve(monkeypatch, **override) == 1
    assert message in capsys.readouterr().err


def test_serve_refuses_remote_db_without_tls(monkeypatch, capsys):
    assert _run_serve(monkeypatch, database_url=REMOTE_DB) == 1
    err = capsys.readouterr().err
    assert "TLS" in err and "Zq7-pw" not in err


def test_serve_refuses_bad_port(monkeypatch, capsys):
    monkeypatch.setenv("PORT", "abc")
    assert _run_serve(monkeypatch) == 1
    assert "PORT" in capsys.readouterr().err


def test_serve_starts_with_proxy_options(monkeypatch):
    calls: dict = {}
    monkeypatch.setenv("PORT", "9090")
    monkeypatch.setattr(
        serve_cli,
        "get_settings",
        lambda: Settings(_env_file=None, trust_proxy=True, **GOOD),  # type: ignore[arg-type]
    )
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.update(kw))
    monkeypatch.setattr(serve_cli.runs, "reap_stale_runs_at_startup", lambda: None)
    serve_cli.serve()
    assert calls["host"] == "0.0.0.0" and calls["port"] == 9090 and calls["workers"] == 1  # noqa: S104
    # uvicorn's own proxy handling trusts the client-controlled first X-Forwarded-For entry.
    assert calls["proxy_headers"] is False and "forwarded_allow_ips" not in calls


# --- forwarded client address (unit) ----------------------------------------------------------
@pytest.mark.parametrize(
    ("header", "hops", "expected"),
    [
        ("203.0.113.9", 1, "203.0.113.9"),
        ("1.2.3.4, 203.0.113.9", 1, "203.0.113.9"),  # spoofed first entry ignored
        ("1.2.3.4, 203.0.113.9, 10.0.0.1", 2, "203.0.113.9"),
        ("203.0.113.9:4711", 1, "203.0.113.9"),
        ("[2001:db8::1]:443", 1, "2001:db8::1"),
        ("2001:db8::1", 1, "2001:db8::1"),
        ("not-an-ip", 1, None),
        ("203.0.113.9", 2, None),
        ("", 1, None),
    ],
)
def test_forwarded_client(header: str, hops: int, expected: str | None):
    assert forwarded_client(header, hops) == expected


def test_forwarded_middleware_uses_the_proxy_entry():
    import asyncio

    seen: dict = {}

    async def app(scope, receive, send):
        seen.update(client=scope["client"], scheme=scope["scheme"])

    mw = ForwardedClientMiddleware(app, hops=1)
    scope = {
        "type": "http",
        "scheme": "http",
        "client": ("169.254.1.1", 5000),
        "headers": [(b"x-forwarded-for", b"6.6.6.6, 203.0.113.9")],
    }
    asyncio.run(mw(scope, None, None))
    assert seen == {"client": ("203.0.113.9", 0), "scheme": "https"}


def test_forwarded_middleware_only_when_hosted_and_trusted():
    from app.api.main import create_app

    def kinds(**kw: object) -> set[str]:
        app = create_app(make(**kw))
        return {m.cls.__name__ for m in app.user_middleware}

    assert "ForwardedClientMiddleware" not in kinds(trust_proxy=True)  # local: never
    assert "ForwardedClientMiddleware" not in kinds(**HOSTED)
    assert "ForwardedClientMiddleware" in kinds(**HOSTED, trust_proxy=True)
