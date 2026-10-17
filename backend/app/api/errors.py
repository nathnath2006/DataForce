"""Exception -> HTTP mapping (contract: owned by the tech lead). Every error body is
`{"error": {"code", "message"}}`; messages never carry secrets, tokens, SQL or stack traces."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.enrichment.errors import EnrichmentConfigError, EnrichmentError, PaidLookupRefused
from app.services.errors import AlreadyExistsError, InvalidInputError, NotFoundError

log = logging.getLogger(__name__)

_HTTP_CODES = {404: "not_found", 403: "forbidden", 409: "conflict", 422: "invalid_input"}


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _validation_message(exc: RequestValidationError) -> str:
    # Field paths and pydantic's message only: never the submitted value (a note body, a name).
    parts = []
    for err in exc.errors()[:10]:
        loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path"))
        parts.append(f"{loc or 'request'}: {err.get('msg', 'invalid')}")
    return "; ".join(parts) or "invalid request"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return error_response(404, "not_found", str(exc))

    @app.exception_handler(InvalidInputError)
    async def _invalid(_: Request, exc: InvalidInputError) -> JSONResponse:
        return error_response(422, "invalid_input", str(exc))

    @app.exception_handler(AlreadyExistsError)
    async def _exists(_: Request, exc: AlreadyExistsError) -> JSONResponse:
        return error_response(409, "conflict", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(422, "invalid_input", _validation_message(exc))

    @app.exception_handler(PaidLookupRefused)
    async def _paid(_: Request, exc: PaidLookupRefused) -> JSONResponse:
        return error_response(409, "paid_lookup_refused", str(exc))

    @app.exception_handler(EnrichmentConfigError)
    async def _not_configured(_: Request, exc: EnrichmentConfigError) -> JSONResponse:
        return error_response(409, "connector_not_configured", str(exc))

    @app.exception_handler(EnrichmentError)
    async def _connector(_: Request, exc: EnrichmentError) -> JSONResponse:
        # EnrichmentError messages are already sanitised by app.enrichment (SR2-11).
        return error_response(502, "connector_error", str(exc))

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        log.warning("integrity error: %s", type(exc.orig).__name__)
        return error_response(409, "conflict", "the change conflicts with existing data")

    @app.exception_handler(SQLAlchemyError)
    async def _db(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        log.error("database error: %s", type(exc).__name__)
        return error_response(500, "internal", "database error")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        fallback = "internal" if exc.status_code >= 500 else "conflict"
        code = _HTTP_CODES.get(exc.status_code, fallback)
        detail = exc.detail if isinstance(exc.detail, str) else "request refused"
        return error_response(exc.status_code, code, detail)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled %s", type(exc).__name__)  # no message: it may quote data
        return error_response(500, "internal", "internal error")
