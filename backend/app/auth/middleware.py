"""Session check for every /api request.

Why a middleware and not a router dependency: it covers every current and future route (including
ones that forget a dependency, and unknown paths) from one place, so a new route cannot ship
open by mistake. It opens its DB session through `get_db` (honouring test overrides), and leaves
the user id in `request.state.user_id` for `get_workspace` / `get_viewer`.
"""

from __future__ import annotations

import json
from http.cookies import SimpleCookie

from anyio import to_thread
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth import sessions

# Exact paths that need no session: liveness, the sign-in flow, and the OAuth redirects (their
# state is bound to the member who started them; the provider's redirect carries our cookie too).
EXEMPT = frozenset(
    {
        "/api/health",
        "/api/auth/status",
        "/api/auth/setup",
        "/api/auth/login",
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
        user_id = await to_thread.run_sync(self._lookup, scope)
        scope.setdefault("state", {})["user_id"] = user_id
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
        await self.app(scope, receive, send)

    @staticmethod
    def _lookup(scope: Scope):
        token = cookie_token(scope)
        if not token:
            return None
        from app.api.deps import get_db  # late: deps imports this package

        app = scope["app"]
        factory = app.dependency_overrides.get(get_db, get_db)
        gen = factory()
        db = next(gen)
        try:
            user = sessions.resolve(db, token)
            return user.id if user else None
        finally:
            gen.close()
