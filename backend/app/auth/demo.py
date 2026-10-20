"""The public demo (docs/M6-ACCOUNTS-ADMIN-CONTRACT.md section E): who a demo visitor can be, what a
demo session may not do, and the limits that keep an open door small.

Every demo path is reachable by anyone on the internet, so the rules here are strict:
* a demo session can only ever become a demo account of the demo workspace;
* anything that touches credentials, people, connectors or limits is refused;
* the visitor's AI key lives only on the session row (sealed) and dies with it.
"""

from __future__ import annotations

import ipaddress
import re
import threading
import time
import uuid
from collections import deque

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth import sessions
from app.config import Settings
from app.db.models import AppUser, Membership, UserAccount, UserSession, Workspace
from app.services import limits as limits_service
from app.services import user_accounts
from app.services.admin import db_size
from app.services.errors import AlreadyExistsError

DEMO_BLOCKED = "not available in the demo"
ADMIN_EMAIL = "demo-admin@demo.invalid"
ADMIN_NAME = "Demo admin"
UPLOAD_MAX_BYTES = 2 * 1024 * 1024
UPLOADS_PER_DAY = 20
UPLOADS_PER_DAY_ALL = 400  # across every visitor, so one flood cannot fill the database
STARTS_PER_HOUR = 20
INFO_KEY = "demo_session_id"  # on the DB session: lets the AI code find the visitor's key

# The write budget below lives in this process's memory: run ONE instance (--max-instances 1). With
# more instances each one counts on its own, so the real limits would be that many times larger.
WRITES_PER_HOUR = 600
WRITES_PER_SESSION = 2000
HEAVY_PER_HOUR = 30
HEAVY_AT_ONCE = 4  # across every demo session
REGISTRY_PER_HOUR = 30
BODY_MAX_BYTES = 20 * 1024
UPLOAD_BODY_MAX_BYTES = UPLOAD_MAX_BYTES + 256 * 1024  # multipart framing; the routes cap the file
FULL_PCT = 70.0
SIZE_CACHE_S = 60.0
PURGE_EVERY_S = 60.0
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_HEAVY = re.compile(
    r"^/api/w/[^/]+/(flows/run|stats/scan|viz/query|themes/run|models|models/[^/]+/score)/?$"
)
_UPLOAD = re.compile(r"^/api/w/[^/]+/(files|accounts/[^/]+/documents)/?$")
_REGISTRY_SEARCH = re.compile(r"^/api/w/[^/]+/registry/search/?$")

_lock = threading.Lock()
_MAX_KEYS = 10_000
_writes: dict[str, deque[float]] = {}
_lifetime: dict[str, int] = {}
_heavy: dict[str, deque[float]] = {}
_registry: dict[str, deque[float]] = {}
_running = 0
_size_cache: tuple[float, float | None] | None = None
_last_purge = 0.0
_starts: dict[str, deque[float]] = {}
_uploads: dict[str, deque[float]] = {}


def client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def is_demo_session(request: Request) -> bool:
    return bool(getattr(request.state, "demo", False))


def require_not_demo(request: Request) -> None:
    """Route dependency: a demo session gets 403 "not available in the demo"."""
    if is_demo_session(request):
        raise HTTPException(status_code=403, detail=DEMO_BLOCKED)


NotDemo = Depends(require_not_demo)  # use as `dependencies=[NotDemo]` on a route


def bind_session(db: Session, request: Request) -> None:
    """Tell the DB session which demo session it serves, so AI calls use that session's key."""
    if is_demo_session(request):
        db.info[INFO_KEY] = getattr(request.state, "session_id", None)


def _hit(table: dict[str, deque[float]], key: str, limit: int, window_s: float) -> bool:
    """Record one use of `key`; False when it already used `limit` in the last `window_s`, or when
    the table is full of live keys and `key` is new (existing buckets are never evicted, so a flood
    of fake keys cannot reset anyone's count)."""
    now = time.monotonic()
    with _lock:
        q = table.get(key)
        if q is None:
            if len(table) >= _MAX_KEYS:
                for k in [k for k, v in table.items() if not v or v[-1] <= now - window_s]:
                    del table[k]
                if len(table) >= _MAX_KEYS:
                    return False
            q = table.setdefault(key, deque())
        while q and q[0] <= now - window_s:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def address_key(client: str) -> str:
    """The rate-limit key of a client address: an IPv6 address counts as its whole /64 (one
    visitor owns a whole /64, so per-address keys would be free to mint); IPv4 as itself."""
    try:
        ip = ipaddress.ip_address(client)
    except ValueError:
        return client
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False).network_address) + "/64"
    return str(ip)


def take_start(client: str) -> bool:
    """One demo start (or identity switch) per call, 20 an hour per client (an IPv6 /64). False
    also when the table is full of live keys (a flood): new starts wait, nobody's count resets."""
    return _hit(_starts, address_key(client), STARTS_PER_HOUR, 3600.0)


def upload_cap(request: Request, normal_max: int, client: str) -> int:
    """The byte limit for one upload. In a demo session it counts the upload (20 a day per client
    address, 400 a day overall) and lowers the limit to 2 MB."""
    if not is_demo_session(request):
        return normal_max
    if not _hit(_uploads, client, UPLOADS_PER_DAY, 86400.0) or not _hit(
        _uploads, "*", UPLOADS_PER_DAY_ALL, 86400.0
    ):
        raise HTTPException(status_code=429, detail="Upload limit reached for today in the demo.")
    return min(normal_max, UPLOAD_MAX_BYTES)


def enforce_size(request: Request, data: bytes) -> None:
    if is_demo_session(request) and len(data) > UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Files are limited to 2 MB in the demo.")


def reset_limits() -> None:
    global _running, _size_cache, _last_purge
    with _lock:
        _starts.clear()
        _uploads.clear()
        _writes.clear()
        _lifetime.clear()
        _heavy.clear()
        _registry.clear()
        _running = 0
        _size_cache = None
        _last_purge = 0.0


# --- write budget (applied by the session middleware to demo sessions only) -----------------------
class Refusal(Exception):
    def __init__(self, status: int, message: str, code: str) -> None:
        self.status, self.message, self.code = status, message, code


def _limit_reached() -> Refusal:
    return Refusal(429, "Demo limit reached — come back later", "rate_limited")


def _used_pct(db: Session, settings: Settings) -> float | None:
    """Share of the effective database quota in use, cached for 60 seconds."""
    global _size_cache
    now = time.monotonic()
    with _lock:
        cached = _size_cache
    if cached is not None and now - cached[0] < SIZE_CACHE_S:
        return cached[1]
    quota = limits_service.effective(db, settings, "db_quota_mb", None)
    used = db_size(db, quota)["used_pct"]
    with _lock:
        _size_cache = (now, used)
    return used


def check_request(
    db: Session, settings: Settings, session_id: object, method: str, path: str, length: int | None
) -> bool:
    """Gate one request of a demo session. Raises Refusal (429, 413 or 503). Returns True when the
    request took a CPU-heavy slot, which the caller must give back with `release_heavy()`.
    Reads (GET) and the sign-in routes are never counted."""
    if method not in MUTATING or path.startswith("/api/auth/"):
        return False
    sid = str(session_id)
    cap = UPLOAD_BODY_MAX_BYTES if _UPLOAD.match(path) else BODY_MAX_BYTES
    if length is None or length > cap:
        raise Refusal(413, "That is too large for the demo.", "payload_too_large")
    used = _used_pct(db, settings)
    if used is not None and used > FULL_PCT:
        raise Refusal(503, "Demo is full until tonight's reset", "unavailable")
    if not _hit(_writes, sid, WRITES_PER_HOUR, 3600.0):
        raise _limit_reached()
    with _lock:
        n = _lifetime.get(sid, 0) + 1
        if n > WRITES_PER_SESSION:
            raise _limit_reached()
        if sid not in _lifetime and len(_lifetime) >= _MAX_KEYS:
            raise _limit_reached()
        _lifetime[sid] = n
    if _REGISTRY_SEARCH.match(path) and not _hit(_registry, sid, REGISTRY_PER_HOUR, 3600.0):
        raise _limit_reached()
    if _HEAVY.match(path) and method == "POST":
        if not _hit(_heavy, sid, HEAVY_PER_HOUR, 3600.0):
            raise _limit_reached()
        global _running
        with _lock:
            if _running >= HEAVY_AT_ONCE:
                raise Refusal(429, "The demo is busy — try again in a moment", "busy")
            _running += 1
        return True
    return False


def release_heavy() -> None:
    global _running
    with _lock:
        _running = max(0, _running - 1)


def purge_expired_sessions(db: Session) -> None:
    """Drop expired demo sessions, at most once a minute per process (cheap enough for every
    session lookup)."""
    global _last_purge
    now = time.monotonic()
    with _lock:
        if _last_purge and now - _last_purge < PURGE_EVERY_S:
            return
        _last_purge = now
    sessions.delete_expired_demo_sessions(db)
    db.commit()


# --- accounts -----------------------------------------------------------------------------------
def demo_workspace(db: Session, settings: Settings) -> Workspace | None:
    """The demo workspace, only when it exists and is a test workspace."""
    ws = db.scalars(
        select(Workspace).where(Workspace.slug == settings.demo_workspace)
    ).one_or_none()
    return ws if ws is not None and ws.is_demo else None


def ensure_accounts(db: Session, ws: Workspace) -> UserAccount:
    """The demo admin (created on first use, admin of `ws`, never a superadmin, no password), and
    every password-less rep account of `ws` marked as a demo account. Returns the demo admin."""
    admin = user_accounts.get_by_email(db, ADMIN_EMAIL)
    if admin is None:
        try:
            with db.begin_nested():
                admin = user_accounts.create_account(
                    db, ADMIN_EMAIL, ADMIN_NAME, None, is_demo=True
                )
        except AlreadyExistsError:
            admin = user_accounts.get_by_email(db, ADMIN_EMAIL)
    if (
        admin is None
        or not admin.is_demo
        or admin.is_admin
        or admin.disabled
        or admin.password_hash is not None
    ):
        raise HTTPException(status_code=409, detail="The demo is not available.")
    member = user_accounts.get_membership(db, admin.id, ws.id)
    if member is None:
        user_accounts.add_membership(db, admin, ws, role="admin")
    elif member.role != "admin":
        member.role = "admin"
    db.execute(
        update(UserAccount)
        .where(
            UserAccount.id.in_(
                select(Membership.user_account_id).where(
                    Membership.workspace_id == ws.id, Membership.app_user_id.is_not(None)
                )
            ),
            UserAccount.password_hash.is_(None),
            UserAccount.is_admin.is_(False),
            UserAccount.is_demo.is_(False),
            ~UserAccount.id.in_(  # never touch someone who also belongs to a real workspace
                select(Membership.user_account_id)
                .join(Workspace, Workspace.id == Membership.workspace_id)
                .where(Workspace.is_demo.is_(False))
            ),
        )
        .values(is_demo=True)
    )
    db.flush()
    return admin


def identities(db: Session, ws: Workspace) -> list[dict[str, str]]:
    """[{as, label, role}] for the "Viewing as" menu: the demo admin, then the reps."""
    out = [{"as": "admin", "label": ADMIN_NAME, "role": "admin"}]
    rows = db.execute(
        select(Membership.app_user_id, Membership.role, AppUser.display_name)
        .join(UserAccount, UserAccount.id == Membership.user_account_id)
        .join(AppUser, AppUser.id == Membership.app_user_id)
        .where(
            Membership.workspace_id == ws.id,
            UserAccount.is_demo.is_(True),
            UserAccount.is_admin.is_(False),
            UserAccount.disabled.is_(False),
        )
        .order_by(AppUser.display_name, AppUser.id)
    )
    for app_user_id, role, name in rows:
        out.append(
            {"as": str(app_user_id), "label": name, "role": "admin" if role == "admin" else "rep"}
        )
    return out


def find_identity(db: Session, ws: Workspace, who: str | None) -> UserAccount | None:
    """The demo account to become: "admin" (default) or the app_user id of a rep of `ws`. Only a
    demo account that is a member of the demo workspace can come back, never anything else."""
    if who is None or who == "admin":
        return ensure_accounts(db, ws)
    try:
        app_user_id = uuid.UUID(who)
    except ValueError:
        return None
    return db.scalars(
        select(UserAccount)
        .join(Membership, Membership.user_account_id == UserAccount.id)
        .where(
            Membership.workspace_id == ws.id,
            Membership.app_user_id == app_user_id,
            UserAccount.is_demo.is_(True),
            UserAccount.is_admin.is_(False),
            UserAccount.disabled.is_(False),
        )
    ).one_or_none()


def session_row(db: Session, request: Request) -> UserSession | None:
    sid = getattr(request.state, "session_id", None)
    return db.get(UserSession, sid) if sid is not None else None
