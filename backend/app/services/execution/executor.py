"""Background execution of runs (decisions D-01, D-02).

`InProcessExecutor` runs jobs on bounded thread pools, one per lane: the default lane runs at
most `max_workers` runs at once; the "llm" lane (Phase 8) runs LLM-backed runs, by default one
at a time, so a Gemini suite paces itself and never starves rule-based runs. Each run gets a
`CancelToken`:
- the agent loop checks it before every step and before every tool call;
- simulated tool latency waits on it, so cancelling interrupts a slow tool immediately;
- a watchdog cancels it with reason "timeout" when a run overruns its limit, and calls an
  `on_overrun` callback that marks the run timed out even if the job is stuck;
- `token.extend(seconds)` pushes the watchdog back, for platform delays that are not the
  agent's time (waiting for the LLM request throttle).

A restart loses in-flight runs; the startup sweeper marks them as orphaned (decision D-10).
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

logger = logging.getLogger(__name__)


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self.reason: str | None = None
        self.extended_s = 0.0  # added to the watchdog limit (platform waits)
        self._extend_lock = threading.Lock()

    def extend(self, seconds: float) -> None:
        if seconds > 0:
            with self._extend_lock:
                self.extended_s += seconds

    def cancel(self, reason: str = "cancelled") -> None:
        if not self._event.is_set():
            self.reason = reason
            self._event.set()

    @property
    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, seconds: float) -> None:
        """Sleep that returns early when the token is cancelled."""
        self._event.wait(max(0.0, seconds))


Job = Callable[[CancelToken], None]


class RunExecutor(Protocol):
    def submit(
        self,
        run_id: uuid.UUID,
        job: Job,
        *,
        timeout_s: float | None = None,
        on_overrun: Callable[[], None] | None = None,
        lane: str = "default",
    ) -> None: ...

    def cancel(self, run_id: uuid.UUID, reason: str = "cancelled") -> bool: ...

    def shutdown(self) -> None: ...


class InProcessExecutor:
    def __init__(
        self, max_workers: int = 2, *, llm_workers: int = 1, watchdog_grace_s: float = 15.0
    ) -> None:
        self.max_workers = max_workers
        self.llm_workers = llm_workers
        self.watchdog_grace_s = watchdog_grace_s
        self._pools = {
            "default": ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="run"),
            "llm": ThreadPoolExecutor(max_workers=llm_workers, thread_name_prefix="llm-run"),
        }
        self._tokens: dict[uuid.UUID, CancelToken] = {}
        self._lock = threading.Lock()
        self.active = 0
        self.peak_active = 0
        self.active_by_lane: dict[str, int] = {"default": 0, "llm": 0}
        self.peak_by_lane: dict[str, int] = {"default": 0, "llm": 0}

    def submit(
        self,
        run_id: uuid.UUID,
        job: Job,
        *,
        timeout_s: float | None = None,
        on_overrun: Callable[[], None] | None = None,
        lane: str = "default",
    ) -> None:
        token = CancelToken()
        with self._lock:
            self._tokens[run_id] = token
        pool = self._pools.get(lane, self._pools["default"])
        pool.submit(self._run, run_id, job, token, timeout_s, on_overrun, lane)

    def _watch(
        self,
        run_id: uuid.UUID,
        token: CancelToken,
        limit_s: float,
        done: threading.Event,
        on_overrun: Callable[[], None] | None,
    ) -> None:
        started = time.monotonic()
        while True:
            remaining = started + limit_s + token.extended_s - time.monotonic()
            if remaining <= 0:
                break
            if done.wait(min(remaining, 1.0)):
                return
        logger.warning("Run %s exceeded its time limit; cancelling", run_id)
        token.cancel("timeout")
        if on_overrun is not None:
            on_overrun()

    def _run(
        self,
        run_id: uuid.UUID,
        job: Job,
        token: CancelToken,
        timeout_s: float | None,
        on_overrun: Callable[[], None] | None,
        lane: str,
    ) -> None:
        with self._lock:
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
            self.active_by_lane[lane] = self.active_by_lane.get(lane, 0) + 1
            self.peak_by_lane[lane] = max(self.peak_by_lane.get(lane, 0), self.active_by_lane[lane])
        done = threading.Event()
        if timeout_s is not None:
            threading.Thread(
                target=self._watch,
                args=(run_id, token, timeout_s + self.watchdog_grace_s, done, on_overrun),
                daemon=True,
                name=f"watchdog-{run_id}",
            ).start()
        try:
            job(token)
        except Exception:  # a job must never take the worker thread down
            logger.exception("Run %s failed outside the agent loop", run_id)
        finally:
            done.set()
            with self._lock:
                self.active -= 1
                self.active_by_lane[lane] -= 1
                self._tokens.pop(run_id, None)

    def cancel(self, run_id: uuid.UUID, reason: str = "cancelled") -> bool:
        with self._lock:
            token = self._tokens.get(run_id)
        if token is None:
            return False
        token.cancel(reason)
        return True

    def shutdown(self) -> None:
        # Pending runs are left queued in the database; the sweeper handles them on restart.
        for pool in self._pools.values():
            pool.shutdown(wait=False, cancel_futures=True)


class InlineExecutor:
    """Runs each job synchronously at submit time. Used by tests and scripts."""

    def __init__(self) -> None:
        self.tokens: dict[uuid.UUID, CancelToken] = {}

    def submit(
        self,
        run_id: uuid.UUID,
        job: Job,
        *,
        timeout_s: float | None = None,
        on_overrun: Callable[[], None] | None = None,
        lane: str = "default",
    ) -> None:
        token = self.tokens.setdefault(run_id, CancelToken())
        job(token)

    def cancel(self, run_id: uuid.UUID, reason: str = "cancelled") -> bool:
        token = self.tokens.get(run_id)
        if token is None:
            return False
        token.cancel(reason)
        return True

    def shutdown(self) -> None:
        return None
