"""Filling a new test workspace with synthetic data in a background thread.

The progress lives in this process only (one process, one instance: hosting plan section 2 item 9).
If the server restarts mid-fill the registry is empty while the row still says 'preparing'; the
setup status then reports `interrupted` and the admin removes the workspace and starts again.
Only one fill runs at a time. The thread uses its own session, never the request's.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, sessionmaker

from app.demo.activities import backfill_workspace
from app.demo.generator import generate
from app.demo.loader import load_dataset
from app.services import workspaces
from app.services.demo_logins import backfill_logins

log = logging.getLogger(__name__)

# Stable ids and English labels, in order. The loader reports the first six, this module the rest.
STEPS: tuple[tuple[str, str], ...] = (
    ("workspace", "Creating the workspace"),
    ("people", "Adding the sales team"),
    ("companies", "Companies and accounts"),
    ("contacts", "Contacts"),
    ("deals", "Deals"),
    ("meetings", "Notes and meeting transcripts"),
    ("activity", "Stage history, activities and tasks"),
    ("logins", "Demo sign-ins"),
)
TOTAL = len(STEPS)
FAILED_MESSAGE = "Preparing the test workspace failed; nothing was kept."
FAILED_KEPT_S = 10 * 60  # a failed entry stays this long so the page can show why
TEST_SEED = 42

_STEP_INDEX = {step_id: i for i, (step_id, _) in enumerate(STEPS)}


@dataclass
class Progress:
    state: str = "preparing"  # preparing | failed
    step: str | None = None
    done: int = 0
    error: str | None = None
    finished_at: float | None = None
    thread: threading.Thread | None = field(default=None, repr=False)


_lock = threading.Lock()
_jobs: dict[str, Progress] = {}


def _purge_locked() -> None:
    now = time.monotonic()
    for slug in [
        s
        for s, p in _jobs.items()
        if p.finished_at is not None and now - p.finished_at > FAILED_KEPT_S
    ]:
        del _jobs[slug]


def reserve(slug: str) -> bool:
    """Claim the single fill slot for `slug`. False when a fill is already running."""
    with _lock:
        _purge_locked()
        if any(p.state == "preparing" for p in _jobs.values()):
            return False
        _jobs[slug] = Progress()
        return True


def release(slug: str) -> None:
    """Give the slot back when the workspace could not be created."""
    with _lock:
        _jobs.pop(slug, None)


def get(slug: str) -> Progress | None:
    with _lock:
        _purge_locked()
        p = _jobs.get(slug)
        return None if p is None else Progress(p.state, p.step, p.done, p.error, p.finished_at)


def is_running(slug: str | None = None) -> bool:
    with _lock:
        return any(p.state == "preparing" and (slug is None or s == slug) for s, p in _jobs.items())


def _set_step(slug: str, step_id: str) -> None:
    with _lock:
        p = _jobs.get(slug)
        if p is not None:
            p.step, p.done = step_id, _STEP_INDEX[step_id]


def _finish(slug: str, error: str | None) -> None:
    with _lock:
        if error is None:
            _jobs.pop(slug, None)  # ready: the row says so
        else:
            p = _jobs.setdefault(slug, Progress())
            p.state, p.step, p.error, p.finished_at = "failed", None, error, time.monotonic()


def join(timeout: float | None = None) -> None:
    """Wait for the running fill thread(s). For tests."""
    with _lock:
        threads = [p.thread for p in _jobs.values() if p.thread is not None]
    for t in threads:
        t.join(timeout)


def _fill_once(slug: str, factory: sessionmaker[Session]) -> None:
    with factory() as s:
        try:
            ws = workspaces.get_workspace_by_slug(s, slug)
            if ws is None:
                raise LookupError("workspace vanished")
            load_dataset(
                s,
                generate("planted", TEST_SEED),
                workspace_slug=slug,
                workspace=ws,
                on_step=lambda step_id: _set_step(slug, step_id),
            )
            _set_step(slug, "activity")
            backfill_workspace(s, slug)
            _set_step(slug, "logins")
            backfill_logins(s, slug)
            ws.setup_state = None
            s.commit()
        except BaseException:
            s.rollback()
            raise


def _remove(slug: str, factory: sessionmaker[Session]) -> None:
    try:
        with factory() as s:
            workspaces.delete_workspace(s, slug)
            s.commit()
    except Exception as cleanup:  # noqa: BLE001
        log.error("test workspace cleanup failed: %s", type(cleanup).__name__)


def _fill(slug: str, factory: sessionmaker[Session]) -> None:
    # `finally` frees the slot on every exit, even a BaseException that skips the cleanup.
    error: str | None = FAILED_MESSAGE
    try:
        _fill_once(slug, factory)
        error = None
    except Exception as exc:  # noqa: BLE001 - any failure must clean up and be reported
        log.error("test workspace fill failed: %s", type(exc).__name__, exc_info=False)
        _remove(slug, factory)
    finally:
        _finish(slug, error)


def start(slug: str, factory: sessionmaker[Session]) -> None:
    """Start the fill thread for a reserved `slug` whose row is committed as 'preparing'."""
    thread = threading.Thread(target=_fill, args=(slug, factory), name=f"fill-{slug}", daemon=True)
    with _lock:
        _jobs[slug].thread = thread
    try:
        thread.start()
    except BaseException:  # no thread: free the slot and drop the empty row, never leave it stuck
        _remove(slug, factory)
        _finish(slug, FAILED_MESSAGE)
        raise
