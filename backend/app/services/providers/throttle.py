"""Process-wide request throttle for LLM calls (decision D-16).

A sliding one-minute window: at most `rpm` requests start in any 60 s. Callers that would
exceed it wait (on an interruptible sleep) until a slot frees up, but never past their
deadline, so a throttled call cannot push a run past its own timeout.
"""

import threading
import time
from collections import deque
from collections.abc import Callable

from app.services.providers.errors import ProviderQuotaError

WINDOW_S = 60.0


class RequestThrottle:
    def __init__(self, rpm: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        if rpm < 1:
            raise ValueError("rpm must be at least 1")
        self.rpm = rpm
        self._clock = clock
        self._starts: deque[float] = deque()
        self._lock = threading.Lock()

    def _reserve(self) -> float:
        """Takes a slot and returns 0, or returns how long to wait before trying again."""
        with self._lock:
            now = self._clock()
            while self._starts and now - self._starts[0] >= WINDOW_S:
                self._starts.popleft()
            if len(self._starts) < self.rpm:
                self._starts.append(now)
                return 0.0
            return self._starts[0] + WINDOW_S - now

    def acquire(
        self,
        *,
        sleep: Callable[[float], None],
        deadline: float | None = None,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        while True:
            wait = self._reserve()
            if wait <= 0:
                return
            if deadline is not None and self._clock() + wait > deadline:
                raise ProviderQuotaError(
                    f"Local Gemini throttle ({self.rpm}/min) has no free slot before the run's "
                    "deadline"
                )
            sleep(wait)
            if should_stop():
                raise ProviderQuotaError("Stopped while waiting for the Gemini throttle")

    def used(self) -> int:
        with self._lock:
            now = self._clock()
            return sum(1 for t in self._starts if now - t < WINDOW_S)
