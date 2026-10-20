"""Session check for every /api request.

Why a middleware and not a router dependency: it covers every current and future route (including
ones that forget a dependency, and unknown paths) from one place, so a new route cannot ship
open by mistake. It opens its DB session through `get_db` (honouring test overrides), and leaves
the user id in `request.state.user_id` (and the session id and demo flag beside it) for
`get_workspace` / `get_viewer`.
"""

from __future__ import annotations

import json
from http.cookies import SimpleCookie

from anyio import to_thread
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth import demo, sessions

# Exact paths that need no session: liveness, the sign-in flow, and the OAuth redirects (their
# state is bound to the member who started them; the provider's redirect carries our cookie too).
EXEMPT = frozenset(
    {
        "/api/health",
        "/api/auth/status",
        "/api/auth/setup",
        "/api/auth/login",
        "/api/auth/demo",
        "/api/auth/signup",
        "/api/auth/forgot",
        "/api/auth/reset",
        "/api/connectors/tamtam/callback",
        "/api/mailbox/callback",
    }
)


def cookie_token(scope: Scope) -> str | None:
    for key, value in scope["headers"]:
        if key == b"cookie":
            jar: SimpleCookie = SimpleCookie()
            try:
                jar.load(value.decode("latin-1"))
            except Exception:  # noqa: BLE001 - a malformed cookie is just "no session"
                return None
            morsel = jar.get(sessions.COOKIE)
            return morsel.value if morsel else None
    return None


class SessionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path == "/api" or path.startswith("/api/")):
            await self.app(scope, receive, send)
            return
        user_id, session_id, is_demo, refusal = await to_thread.run_sync(self._lookup, scope)
        state = scope.setdefault("state", {})
        state["user_id"] = user_id
        state["session_id"] = session_id
        state["demo"] = is_demo
        if refusal is not None and not isinstance(refusal, bool):
            await self._refuse(send, refusal.status, refusal.message, refusal.code)
            return
        if user_id is None and path not in EXEMPT:
            body = json.dumps(
                {"error": {"code": "unauthorized", "message": "sign in required"}}
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        try:
            await self.app(scope, receive, send)
        finally:
            if refusal is True:  # this request held a CPU-heavy demo slot
                demo.release_heavy()

    @staticmethod
    async def _refuse(send: Send, status: int, message: str, code: str) -> None:
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

    @staticmethod
    def _lookup(scope: Scope):
        """(user id, session id, is demo, gate). The gate is None, True (a heavy slot is held) or
        a demo.Refusal."""
        token = cookie_token(scope)
        if not token:
            return None, None, False, None
        from app.api.deps import get_db  # late: deps imports this package
        from app.config import get_settings

        app = scope["app"]
        factory = app.dependency_overrides.get(get_db, get_db)
        gen = factory()
        db = next(gen)
        try:
            found = sessions.resolve_session(db, token)
            if found is None:
                return None, None, False, None
            user, row = found
            if not row.is_demo:
                return user.id, row.id, False, None
            demo.purge_expired_sessions(db)
            settings = getattr(app.state, "settings", None) or get_settings()
            headers = dict(scope["headers"])
            length: int | None = 0  # no length and no chunking: no body
            if b"content-length" in headers:
                try:
                    length = int(headers[b"content-length"])
                except ValueError:
                    length = None
            elif b"transfer-encoding" in headers:
                length = None  # chunked: the size cannot be checked up front
            gate: object = None
            try:
                gate = demo.check_request(
                    db, settings, row.id, scope.get("method", "GET"), scope.get("path", ""), length
                )
            except demo.Refusal as refusal:
                gate = refusal
            return user.id, row.id, True, gate or None
        finally:
            gen.close()
