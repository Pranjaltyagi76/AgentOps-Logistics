"""The thread-pool executor: concurrency limit, cancel tokens and the watchdog (no database)."""

import threading
import time
import uuid

from app.services.execution.executor import CancelToken, InProcessExecutor


def _wait_until(condition, timeout: float = 5.0) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not met in time"
        time.sleep(0.01)


def test_at_most_max_workers_runs_execute_at_once() -> None:
    executor = InProcessExecutor(max_workers=2)
    release = threading.Event()
    started: list[uuid.UUID] = []
    finished: list[uuid.UUID] = []
    lock = threading.Lock()

    def job_for(run_id: uuid.UUID):  # type: ignore[no-untyped-def]
        def job(token: CancelToken) -> None:
            with lock:
                started.append(run_id)
            release.wait(5)
            with lock:
                finished.append(run_id)

        return job

    ids = [uuid.uuid4() for _ in range(5)]
    for run_id in ids:
        executor.submit(run_id, job_for(run_id))
    _wait_until(lambda: len(started) == 2)
    time.sleep(0.1)
    assert len(started) == 2 and executor.active == 2  # the other 3 wait in the queue
    release.set()
    _wait_until(lambda: len(finished) == 5)
    assert executor.peak_active == 2
    assert sorted(started) == sorted(ids)
    executor.shutdown()


def test_cancelling_a_queued_run_reaches_its_job() -> None:
    executor = InProcessExecutor(max_workers=1)
    release = threading.Event()
    seen: dict[str, str | None] = {}

    executor.submit(uuid.uuid4(), lambda token: release.wait(5))
    queued = uuid.uuid4()
    executor.submit(queued, lambda token: seen.setdefault("reason", token.reason))
    assert executor.cancel(queued) is True
    release.set()
    _wait_until(lambda: "reason" in seen)
    assert seen["reason"] == "cancelled"
    assert executor.cancel(uuid.uuid4()) is False  # unknown run
    executor.shutdown()


def test_watchdog_cancels_with_timeout_and_calls_overrun() -> None:
    executor = InProcessExecutor(max_workers=1, watchdog_grace_s=0.0)
    overrun = threading.Event()
    reasons: list[str | None] = []

    def stuck(token: CancelToken) -> None:
        token.wait(5)  # returns as soon as the watchdog cancels
        reasons.append(token.reason)

    executor.submit(uuid.uuid4(), stuck, timeout_s=0.05, on_overrun=overrun.set)
    _wait_until(lambda: reasons)
    assert overrun.is_set()
    assert reasons == ["timeout"]
    executor.shutdown()


def test_job_exceptions_do_not_kill_the_worker() -> None:
    executor = InProcessExecutor(max_workers=1)
    done = threading.Event()

    def boom(token: CancelToken) -> None:
        raise RuntimeError("boom")

    executor.submit(uuid.uuid4(), boom)
    executor.submit(uuid.uuid4(), lambda token: done.set())
    _wait_until(done.is_set)
    executor.shutdown()


def test_cancel_token_wait_is_interruptible() -> None:
    token = CancelToken()
    threading.Timer(0.05, token.cancel).start()
    started = time.monotonic()
    token.wait(5)
    assert time.monotonic() - started < 2
    assert token.reason == "cancelled"
    token.cancel("timeout")  # first reason wins
    assert token.reason == "cancelled"
