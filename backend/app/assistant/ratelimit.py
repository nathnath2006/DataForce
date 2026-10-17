"""In-process sliding-window limit on assistant calls per workspace (SR10-04)."""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict, deque

from app.services.errors import AlreadyExistsError

WINDOW_S = 3600.0
_hits: dict[uuid.UUID, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def check_and_count(ws_id: uuid.UUID, limit: int, *, now: float | None = None) -> None:
    """Count one call for the workspace, or raise (409 conflict) when `limit` was reached in the
    last hour. A refused call is not counted."""
    t = time.monotonic() if now is None else now
    with _lock:
        q = _hits[ws_id]
        while q and q[0] <= t - WINDOW_S:
            q.popleft()
        if len(q) >= limit:
            raise AlreadyExistsError(f"too many questions this hour (limit {limit})")
        q.append(t)


def reset() -> None:
    with _lock:
        _hits.clear()
