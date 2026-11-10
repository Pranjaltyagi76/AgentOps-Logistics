"""Measure API and run latency against the local database (context/performance_review.md §5).

Usage (from backend/, database migrated and seeded):
    uv run python ../scripts/perf_probe.py            # 20 samples per measurement
    uv run python ../scripts/perf_probe.py --samples 50

Runs execute inline (no thread pool) so their timing is the agent run itself. Creates real
runs in the database you point it at; use a development database. Prints JSON.
"""

import argparse
import json
import statistics
import sys
import time
from collections.abc import Callable

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from app.services.execution.executor import InlineExecutor


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * len(ordered)) - 1))
    return ordered[index]


def measure(fn: Callable[[], object], samples: int, warmup: int = 3) -> dict[str, float]:
    for _ in range(warmup):
        fn()
    timings = []
    for _ in range(samples):
        started = time.perf_counter()
        fn()
        timings.append((time.perf_counter() - started) * 1000)
    return {
        "p50_ms": round(statistics.median(timings), 1),
        "p95_ms": round(percentile(timings, 95), 1),
        "max_ms": round(max(timings), 1),
        "n": samples,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", type=int, default=20)
    args = parser.parse_args(argv)

    settings = get_settings().model_copy(update={"run_rate_limit_per_minute": 10_000})
    with TestClient(create_app(settings, executor=InlineExecutor())) as client:
        token = client.post("/api/v1/auth/demo").json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        scenarios = client.get("/api/v1/scenarios", params={"limit": 50}, headers=h).json()["items"]
        scenario = next(s for s in scenarios if s["scenario_key"] == "delay_hub_congestion_001")
        agent = next(
            a
            for a in client.get("/api/v1/agents", headers=h).json()
            if a["name"] == "rule-based-v1"
        )
        body = {"scenario_id": scenario["id"], "agent_config_id": agent["id"]}

        run_ids: list[str] = []

        def launch() -> None:
            response = client.post("/api/v1/runs", json=body, headers=h)
            assert response.status_code == 202, response.text
            run_ids.append(response.json()["id"])

        results = {
            "health": measure(lambda: client.get("/api/v1/health"), args.samples),
            "list_scenarios_20": measure(
                lambda: client.get("/api/v1/scenarios", headers=h), args.samples
            ),
            "rule_based_run_inline": measure(launch, args.samples, warmup=1),
        }
        run_id = run_ids[-1]
        results["get_run"] = measure(
            lambda: client.get(f"/api/v1/runs/{run_id}", headers=h), args.samples
        )
        results["get_trace"] = measure(
            lambda: client.get(f"/api/v1/runs/{run_id}/trace", headers=h), args.samples
        )
        results["list_runs_25"] = measure(
            lambda: client.get("/api/v1/runs", headers=h), args.samples
        )
        events = client.get(f"/api/v1/runs/{run_id}/trace", headers=h).json()["events"]
        results["trace_events_per_run"] = {"count": len(events)}
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
