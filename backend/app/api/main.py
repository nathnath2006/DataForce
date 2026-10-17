"""App factory (contract: owned by the tech lead). Run with `dataforce ui`."""

from __future__ import annotations

from fastapi import FastAPI

from app import __version__
from app.api.errors import install_error_handlers
from app.api.routes import connectors, crm, enrichment, notes, stats, workspaces
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

    for module in (workspaces, crm, notes, stats, connectors, enrichment):
        app.include_router(module.router, prefix="/api")
    install_security(app, settings)  # last added = outermost middleware
    install_static(app, settings)  # SPA at /, after the API routes
    return app
