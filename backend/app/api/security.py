"""Request guards for a loopback app without login (docs/UI-CONTRACT.md section 2).

A pure ASGI middleware, so it also sees the requests that never reach a route:

1. Host allow-list (DNS rebinding): 127.0.0.1 / localhost / [::1] on the UI or the Vite port.
2. POST / PUT / PATCH / DELETE need an allowed `Origin` and `X-DataForce: 1` (no CORS is
   installed: another website cannot drive the API, its preflight fails).
3. Request bodies must be application/json and at most 256 KB.
4. Security headers on every response; `Cache-Control: no-store` under /api.
"""

from __future__ import annotations

import json
import logging
import re

from fastapi import FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings

log = logging.getLogger(__name__)

MAX_BODY_BYTES = 256 * 1024
VITE_PORT = 5173
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_HEADER = "x-dataforce"
UPLOAD_PATH = re.compile(
    r"^/api/w/[a-z0-9][a-z0-9-]{0,63}/(?:files|accounts/[0-9a-fA-F-]{36}/documents)$"
)
MULTIPART_OVERHEAD = 64 * 1024  # form framing around the file

SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (
        b"content-security-policy",
        b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        b"connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    ),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
)


def allowed_hosts(settings: Settings) -> frozenset[str]:
    ports = {settings.ui_port, VITE_PORT}
    return frozenset(
        f"{name}:{port}" for port in ports for name in ("127.0.0.1", "localhost", "[::1]")
    )


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.hosts = allowed_hosts(settings)
        self.origins = frozenset(o.lower() for o in settings.ui_allowed_origins)
        self.upload_limit = settings.upload_max_bytes + MULTIPART_OVERHEAD
        self.transcript_limit = settings.transcript_max_bytes + MULTIPART_OVERHEAD

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = scope["path"] == "/api" or scope["path"].startswith("/api/")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in {name for name, _ in SECURITY_HEADERS}
                ]
                headers.extend(SECURITY_HEADERS)
                if is_api:
                    headers = [(k, v) for k, v in headers if k.lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        refusal = self._refusal(scope)
        if refusal is not None:
            status, code, text = refusal
            await self._respond(send_with_headers, status, code, text)
            return

        too_large = False
        received = 0
        body_limit = self._body_limit(scope)

        async def guarded_send(message: Message) -> None:
            if too_large:  # the app saw a cut-off body: its answer is replaced by the 413
                return
            await send_with_headers(message)

        async def limited_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > body_limit:
                    too_large = True
                    return {"type": "http.disconnect"}
            return message

        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start" and not too_large:
                started = True
            await guarded_send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except Exception as exc:  # swallow: Starlette / uvicorn would log message + traceback
            log.error("unhandled %s", type(exc).__name__)  # type only: the message may quote data
            if started:
                return  # too late to answer; the connection ends with what was sent
            if not too_large:
                await self._respond(send_with_headers, 500, "internal", "internal error")
                return
        if too_large:
            await self._respond(send_with_headers, 413, "invalid_input", "request body too large")

    def _is_upload(self, scope: Scope) -> bool:
        return scope["method"] == "POST" and UPLOAD_PATH.match(scope["path"]) is not None

    def _body_limit(self, scope: Scope) -> int:
        if not self._is_upload(scope):
            return MAX_BODY_BYTES
        if scope["path"].endswith("/documents"):
            return self.transcript_limit
        return self.upload_limit

    def _refusal(self, scope: Scope) -> tuple[int, str, str] | None:
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        names = [k.lower() for k, _ in scope["headers"]]
        if names.count(b"host") > 1:
            return 400, "invalid_input", "duplicate Host header"
        if names.count(b"origin") > 1 or names.count(CSRF_HEADER.encode()) > 1:
            return 403, "forbidden", "duplicate Origin / X-DataForce header"
        if headers.get("host", "").lower() not in self.hosts:
            return 400, "invalid_input", "unexpected Host header"
        method = scope["method"]
        if method in UNSAFE_METHODS:
            origin = headers.get("origin", "").lower()
            if origin not in self.origins or headers.get(CSRF_HEADER) != "1":
                return 403, "forbidden", "cross-site or missing origin / X-DataForce header"
        has_body = headers.get("transfer-encoding") is not None or headers.get(
            "content-length", "0"
        ).strip() not in ("", "0")
        if has_body:
            media = headers.get("content-type", "").split(";")[0].strip().lower()
            upload = self._is_upload(scope)
            want = "multipart/form-data" if upload else "application/json"
            if media != want:
                return 415, "invalid_input", f"the body must be {want}"
            try:
                length = int(headers.get("content-length", "0") or 0)
            except ValueError:
                return 400, "invalid_input", "invalid Content-Length"
            if length > self._body_limit(scope):
                return 413, "invalid_input", "request body too large"
        return None

    @staticmethod
    async def _respond(send: Send, status: int, code: str, message: str) -> None:
        body = json.dumps({"error": {"code": code, "message": message}}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def install_security(app: FastAPI, settings: Settings) -> None:
    from app.auth.middleware import SessionMiddleware

    app.add_middleware(SessionMiddleware)  # inside the guard: its 401 gets the security headers
    app.add_middleware(SecurityMiddleware, settings=settings)
