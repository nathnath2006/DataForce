"""In-process login failure limits: 10 per email and 50 per client per 15 minutes."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.services.errors import ServiceError

WINDOW_S = 15 * 60.0
PER_EMAIL = 10
PER_CLIENT = 50
_fails: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


class TooManyAttempts(ServiceError):
    pass


def _count(key: str, now: float) -> int:
    q = _fails[key]
    while q and q[0] <= now - WINDOW_S:
        q.popleft()
    return len(q)


def check(email: str, client: str, *, now: float | None = None) -> None:
    t = time.monotonic() if now is None else now
    with _lock:
        if _count(f"e:{email}", t) >= PER_EMAIL or _count(f"c:{client}", t) >= PER_CLIENT:
            raise TooManyAttempts("too many failed sign-in attempts; try again later")


def record_failure(email: str, client: str, *, now: float | None = None) -> None:
    t = time.monotonic() if now is None else now
    with _lock:
        _fails[f"e:{email}"].append(t)
        _fails[f"c:{client}"].append(t)


def clear_email(email: str) -> None:
    with _lock:
        _fails.pop(f"e:{email}", None)


def reset() -> None:
    with _lock:
        _fails.clear()
