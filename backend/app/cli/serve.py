"""`dataforce serve`: run the hosted app behind the platform's HTTPS front end (Cloud Run)."""

from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

import typer
from pydantic import ValidationError

from app.cli._common import fail
from app.cli.ui import _DropQueryString
from app.config import check_database_tls, get_settings, parse_database_url
from app.services import runs

DEFAULT_PORT = 8080


def _port() -> int:
    raw = os.environ.get("PORT", "").strip() or str(DEFAULT_PORT)
    if not raw.isdigit() or not 1 <= int(raw) <= 65535:
        raise fail("PORT must be a number between 1 and 65535")
    return int(raw)


def serve() -> None:
    """Start the hosted app on 0.0.0.0:$PORT (default 8080), one worker. No migrations."""
    import uvicorn

    from app.api.main import create_app

    try:
        settings = get_settings()
    except ValidationError as exc:  # field names and our own messages only, never the input
        problems = "; ".join(
            f"{'.'.join(map(str, e['loc'])).upper()}: {e['msg']}" for e in exc.errors()
        )
        raise fail(f"invalid settings ({problems})") from None
    origin = urlsplit(settings.public_origin)
    if not settings.public_origin or origin.scheme != "https":
        raise fail("serve needs PUBLIC_ORIGIN set to the public https:// origin of the app")
    if settings.dataforce_secret_key is None:
        raise fail("serve needs DATAFORCE_SECRET_KEY (generate one with: dataforce secrets init)")
    if settings.environment != "demo":  # dev and test relax the credential and endpoint checks
        raise fail(f"serve refuses ENVIRONMENT={settings.environment}; use ENVIRONMENT=demo")
    try:
        check_database_tls(parse_database_url(settings.database_url.get_secret_value()))
    except ValueError as exc:
        raise fail(str(exc)) from None
    port = _port()
    typer.echo(f"DataForce hosted: {settings.public_origin}  (listening on port {port})")
    logging.getLogger("uvicorn.access").addFilter(_DropQueryString())
    runs.reap_stale_runs_at_startup()
    # Forwarded headers are read by our ForwardedClientMiddleware (TRUST_PROXY), never by uvicorn.
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",  # noqa: S104 - the container's only peer is the platform front end
        port=port,
        workers=1,
        log_level="info",
        proxy_headers=False,
    )
