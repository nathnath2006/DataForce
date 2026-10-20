"""In-process login failure limits: 10 per email and 50 per client per 15 minutes."""

from __future__ import annotations

import threading
import time
from collections import deque

from app.services.errors import ServiceError

WINDOW_S = 15 * 60.0
PER_EMAIL = 10
PER_CLIENT = 50
MAX_KEYS = 10_000
_fails: dict[str, deque[float]] = {}
_lock = threading.Lock()


class TooManyAttempts(ServiceError):
    pass


def _count(key: str, now: float) -> int:
    q = _fails.get(key)
    if q is None:
        return 0
    while q and q[0] <= now - WINDOW_S:
        q.popleft()
    if not q:
        del _fails[key]
        return 0
    return len(q)


def _add(key: str, t: float) -> None:
    if key not in _fails and len(_fails) >= MAX_KEYS:
        for k in [k for k, q in _fails.items() if not q or q[-1] <= t - WINDOW_S]:
            del _fails[k]
        while len(_fails) >= MAX_KEYS:  # still full: evict the oldest window
            del _fails[min(_fails, key=lambda k: _fails[k][0])]
    _fails.setdefault(key, deque()).append(t)


def check(email: str, client: str, *, now: float | None = None) -> None:
    t = time.monotonic() if now is None else now
    with _lock:
        if _count(f"e:{email}", t) >= PER_EMAIL or _count(f"c:{client}", t) >= PER_CLIENT:
            raise TooManyAttempts("too many failed sign-in attempts; try again later")


def record_failure(email: str, client: str, *, now: float | None = None) -> None:
    t = time.monotonic() if now is None else now
    with _lock:
        _add(f"e:{email}", t)
        _add(f"c:{client}", t)


def clear_email(email: str) -> None:
    with _lock:
        _fails.pop(f"e:{email}", None)


def reset() -> None:
    with _lock:
        _fails.clear()
