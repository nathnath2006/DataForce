"""`dataforce ui`: serve the local web UI and API on loopback (no login before M3)."""

from __future__ import annotations

import logging
from typing import Annotated

import typer

from app.cli._common import fail
from app.config import get_settings


class _DropQueryString(logging.Filter):
    """uvicorn's access log prints the full request path; query strings can carry an OAuth
    `code` / `state` (the TamTam callback) or search terms. Log the path only."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], args[2].split("?", 1)[0], *args[3:])
        return True


def ui(
    port: Annotated[
        int | None, typer.Option("--port", min=1024, max=65535, help="Port (default 8800).")
    ] = None,
    no_build_check: Annotated[
        bool, typer.Option("--no-build-check", help="Do not warn when the frontend is not built.")
    ] = False,
) -> None:
    """Start the UI at http://127.0.0.1:8800 (loopback only, one worker)."""
    import uvicorn

    from app.api.main import create_app

    settings = get_settings()
    if settings.environment == "demo":
        raise fail("the UI is not available with ENVIRONMENT=demo: there is no login before M3")
    chosen = port or settings.ui_port
    if port is not None and port != settings.ui_port:
        extra = [f"http://{h}:{port}" for h in ("127.0.0.1", "localhost")]
        origins = [
            *settings.ui_allowed_origins,
            *(o for o in extra if o not in settings.ui_allowed_origins),
        ]
        settings = settings.model_copy(update={"ui_port": port, "ui_allowed_origins": origins})
    if not no_build_check and not (settings.ui_dist_dir / "index.html").is_file():
        typer.echo("note: frontend not built (run `make ui`); serving the API only.", err=True)
    typer.echo(f"DataForce UI: http://127.0.0.1:{chosen}  (Ctrl+C to stop)")
    logging.getLogger("uvicorn.access").addFilter(_DropQueryString())
    uvicorn.run(
        create_app(settings), host=settings.ui_host, port=chosen, workers=1, log_level="info"
    )
