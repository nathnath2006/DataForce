"""Usage accounting + concurrency limit shared by every real provider call.

`CallTimer` times one provider call and emits exactly one `LLMCallRecord` to an optional
`UsageRecorder`. Records carry token counts, latency and a short error label, never the prompt.
"""

from __future__ import annotations

import asyncio
import logging
import time
import weakref
from typing import Literal

from app.domain.ports import UsageRecorder
from app.domain.schemas import LLMCallRecord

log = logging.getLogger(__name__)

Purpose = Literal["title_classification", "theme_naming", "explanation", "embedding"]

# One semaphore per event loop (an asyncio.Semaphore is bound to the loop that first waits on
# it, and tests / `asyncio.run` create several loops in one process). Module-level so every
# provider instance in the process shares the same `llm_max_concurrency` budget.
_SEMAPHORES: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, tuple[int, asyncio.Semaphore]] = (
    weakref.WeakKeyDictionary()
)


def llm_slot(limit: int) -> asyncio.Semaphore:
    """The shared semaphore for the running loop, sized `limit` (settings.llm_max_concurrency).

    Use as `async with llm_slot(n): ...`. If the configured limit changes between calls the
    semaphore is replaced; calls already in flight keep the old one, which is harmless.
    """
    loop = asyncio.get_running_loop()
    current = _SEMAPHORES.get(loop)
    if current is None or current[0] != limit:
        current = (limit, asyncio.Semaphore(max(1, limit)))
        _SEMAPHORES[loop] = current
    return current[1]


def describe_exception(exc: BaseException) -> str:
    """A short, prompt-free label for an SDK exception: class name + HTTP code + status.

    Deliberately omits `str(exc)`: provider error messages can echo request fragments.
    """
    parts = [type(exc).__name__]
    code = getattr(exc, "status_code", None)
    if not isinstance(code, int):
        code = getattr(exc, "code", None)
    if isinstance(code, int):
        parts.append(f"http {code}")
    status = getattr(exc, "status", None)
    if isinstance(status, str) and status.replace("_", "").isalpha() and len(status) <= 40:
        parts.append(status)
    return " ".join(parts)


class CallTimer:
    """Start it right before the provider call; finish it exactly once."""

    def __init__(
        self,
        usage: UsageRecorder | None,
        *,
        provider: str,
        model: str,
        purpose: Purpose,
    ) -> None:
        self._usage = usage
        self._provider = provider
        self._model = model
        self._purpose: Purpose = purpose
        self._t0 = time.perf_counter()
        self._done = False

    def success(self, *, input_tokens: int | None = None, output_tokens: int | None = None) -> None:
        self._emit(True, None, input_tokens, output_tokens)

    def failure(
        self,
        error: str,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        self._emit(False, error[:300], input_tokens, output_tokens)

    def _emit(
        self,
        success: bool,
        error: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        if self._done:
            return
        self._done = True
        if self._usage is None:
            return
        record = LLMCallRecord(
            provider=self._provider,
            model=self._model,
            purpose=self._purpose,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=int((time.perf_counter() - self._t0) * 1000),
            success=success,
            error=error,
        )
        try:
            self._usage.record(record)
        except Exception:  # accounting must never break a pipeline run
            log.warning("usage recorder failed for %s/%s", self._provider, self._model)
