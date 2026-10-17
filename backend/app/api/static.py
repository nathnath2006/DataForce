"""Serve the built frontend at / with a single-page-app fallback (docs/UI-CONTRACT.md section 1).

`/api/**` is never shadowed: an unknown API path stays a JSON 404. Nothing is mounted when the
dist directory (or its index.html) is missing: the app is then API only."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response

from app.api.errors import error_response
from app.config import Settings


def _resolve(dist: Path, relative: str) -> Path | None:
    """The file under `dist` for this URL path, or None (missing, a directory, or an escape)."""
    if "\x00" in relative:
        return None
    try:
        candidate = (dist / relative).resolve()
        candidate.relative_to(dist)
    except (ValueError, OSError):
        return None
    return candidate if candidate.is_file() else None


def install_static(app: FastAPI, settings: Settings) -> None:
    try:
        dist = settings.ui_dist_dir.resolve()
    except OSError:
        return
    index = dist / "index.html"
    if not index.is_file():
        return

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(request: Request, full_path: str) -> Response:
        if full_path == "api" or full_path.startswith("api/"):
            return error_response(404, "not_found", "not found")
        asset = _resolve(dist, full_path) if full_path else None
        if asset is not None:
            return FileResponse(asset)
        last = full_path.rsplit("/", 1)[-1]
        if "." in last:  # looks like a file (app.js, logo.png): a missing one is a real 404
            return error_response(404, "not_found", "not found")
        return FileResponse(index, headers={"cache-control": "no-cache"})
