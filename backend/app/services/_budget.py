"""Shared in-memory AI budget (process-wide, per workspace): a daily call counter and a short
memory of keys whose provider call failed. Each feature owns an instance and its own caps."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Hashable

FAILURE_TTL_S = 3_600.0


def _day() -> int:
    return int(time.time() // 86_400)


class Budget:
    def __init__(self, failure_ttl_s: float = FAILURE_TTL_S) -> None:
        self.ttl = failure_ttl_s
        self.lock = threading.Lock()
        self.daily: dict[tuple[uuid.UUID, int], int] = {}
        self.failed: dict[Hashable, float] = {}

    def reset(self) -> None:
        with self.lock:
            self.daily.clear()
            self.failed.clear()

    def _drop_old_days(self) -> None:
        today = _day()
        for key in [k for k in self.daily if k[1] != today]:
            del self.daily[key]

    def remaining(self, ws_id: uuid.UUID, cap: int) -> int:
        with self.lock:
            self._drop_old_days()
            return max(0, cap - self.daily.get((ws_id, _day()), 0))

    def spend(self, ws_id: uuid.UUID, n: int) -> None:
        with self.lock:
            k = (ws_id, _day())
            self.daily[k] = self.daily.get(k, 0) + n

    def take(self, ws_id: uuid.UUID, cap: int) -> bool:
        """Spend one call if the day's cap allows it."""
        with self.lock:
            self._drop_old_days()
            k = (ws_id, _day())
            if self.daily.get(k, 0) >= cap:
                return False
            self.daily[k] = self.daily.get(k, 0) + 1
            return True

    def recently_failed(self, key: Hashable) -> bool:
        with self.lock:
            at = self.failed.get(key)
            if at is not None and time.monotonic() - at > self.ttl:
                del self.failed[key]
                return False
            return at is not None

    def remember_failure(self, key: Hashable) -> None:
        with self.lock:
            now = time.monotonic()
            for k in [k for k, at in self.failed.items() if now - at > self.ttl]:
                del self.failed[k]
            self.failed[key] = now
