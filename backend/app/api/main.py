"""App factory (contract: owned by the tech lead). Run with `dataforce ui`."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.gzip import GZipMiddleware

from app import __version__
from app.api.errors import install_error_handlers
from app.api.routes import (
    activities,
    admin,
    agent,
    ai,
    companies,
    connectors,
    crm,
    data,
    documents,
    enrichment,
    flows,
    genai,
    notes,
    orgchart,
    pipeline,
    quality,
    saved_models,
    stats,
    themes,
    titles,
    viz,
    workbooks,
    workspaces,
)
from app.api.schemas import Health
from app.api.security import install_security
from app.api.static import install_static
from app.config import Settings, get_settings


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

    @app.get("/api/health", response_model=Health, tags=["meta"])
    def health() -> Health:
        return Health(ok=True, version=__version__, environment=settings.environment)

    routers = (workspaces, crm, notes, stats, connectors, enrichment, companies, data, flows, ai)
    routers += (titles, orgchart, documents, themes)  # M2b
    routers += (agent,)  # M3a
    routers += (quality,)  # data quality
    routers += (admin,)  # admin view
    routers += (viz, workbooks)  # M4 workbooks
    routers += (activities, pipeline)  # M4 activities, tasks, stage control, timeline
    routers += (saved_models, genai)  # M4 phase 2
    for module in routers:
        app.include_router(module.router, prefix="/api")
    app.add_middleware(GZipMiddleware, minimum_size=1000)  # inside security: headers still added
    install_security(app, settings)  # last added = outermost middleware
    install_static(app, settings)  # SPA at /, after the API routes
    return app
