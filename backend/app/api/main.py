"""App factory (contract: owned by the tech lead). Run with `dataforce ui`."""

from __future__ import annotations

import logging
import threading
import time

from fastapi import FastAPI, Response
from sqlalchemy import text
from starlette.middleware.gzip import GZipMiddleware

from app import __version__
from app.api.deps import SessionFactory
from app.api.errors import install_error_handlers
from app.api.routes import (
    access_codes,
    activities,
    admin,
    agent,
    ai,
    auth,
    companies,
    connectors,
    crm,
    data,
    documents,
    enrichment,
    flows,
    genai,
    home,
    mailbox,
    notes,
    orgchart,
    pipeline,
    quality,
    saved_models,
    stats,
    themes,
    titles,
    users,
    viz,
    workbooks,
    workspaces,
)
from app.api.schemas import Health
from app.api.security import install_security
from app.api.static import install_static
from app.config import Settings, get_settings

log = logging.getLogger(__name__)

HEALTH_PROBE_S = 5.0


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="DataForce local API",
        version=__version__,
        # No Swagger page: it loads from a CDN, which the CSP blocks (SR6-04). The machine-readable
        # contract stays at /api/openapi.json.
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    install_error_handlers(app)

    probe_lock = threading.Lock()
    last_probe: list[tuple[float, str]] = []  # (monotonic time, result) of the latest probe

    @app.get("/api/health", response_model=Health, tags=["meta"])
    def health(response: Response, factory: SessionFactory) -> Health:
        # Cheap liveness plus a 2 s database probe, at most one per HEALTH_PROBE_S per process
        # (a flood of calls shares it); no error text, host or URL ever leaves here.
        with probe_lock:
            if last_probe and time.monotonic() - last_probe[0][0] < HEALTH_PROBE_S:
                database = last_probe[0][1]
            else:
                database = "ok"
                try:
                    with factory() as db:
                        db.execute(text("SET LOCAL statement_timeout = 2000"))
                        db.execute(text("SELECT 1"))
                except Exception as exc:  # noqa: BLE001 - the message may quote the target
                    log.warning("health: database check failed (%s)", type(exc).__name__)
                    database = "unavailable"
                last_probe[:] = [(time.monotonic(), database)]
        if database != "ok":
            response.status_code = 503
        return Health(
            ok=database == "ok",
            version=__version__,
            environment=settings.environment,
            database=database,
        )

    routers = (workspaces, crm, notes, stats, connectors, enrichment, companies, data, flows, ai)
    routers += (titles, orgchart, documents, themes)  # M2b
    routers += (agent,)  # M3a
    routers += (quality,)  # data quality
    routers += (admin,)  # admin view
    routers += (viz, workbooks)  # M4 workbooks
    routers += (activities, pipeline)  # M4 activities, tasks, stage control, timeline
    routers += (saved_models, genai, mailbox)  # M4 phase 2
    routers += (home,)  # M5 home dashboard
    routers += (auth, users)  # M5 sign-in and members
    routers += (access_codes,)  # M6 creation codes and join tokens
    for module in routers:
        app.include_router(module.router, prefix="/api")
    app.add_middleware(GZipMiddleware, minimum_size=1000)  # inside security: headers still added
    install_security(app, settings)  # last added = outermost middleware
    install_static(app, settings)  # SPA at /, after the API routes
    return app
