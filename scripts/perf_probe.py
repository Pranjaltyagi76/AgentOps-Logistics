"""Measure API and run latency (context/performance_review.md §5).

Usage:
    # In-process, against the local database (from backend/, migrated and seeded):
    uv run python ../scripts/perf_probe.py            # 20 samples per measurement
    uv run python ../scripts/perf_probe.py --samples 50
    # Over HTTPS against a deployment (standard library only, any directory):
    python scripts/perf_probe.py --api https://agentops-api-pehy.onrender.com --samples 20

In-process, runs execute inline (no thread pool) so their timing is the agent run itself. In
--api mode, timings are client-side over one kept-alive connection (they include the network),
and run latency is the server-recorded `latency_ms` of --runs rule-based runs, waited for one at a
time. Both modes create real runs as the demo viewer. Prints JSON.
"""

import argparse
import http.client
import json
import statistics
import sys
import time
import urllib.parse
from collections.abc import Callable


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


class Remote:
    """A tiny keep-alive HTTPS client (one connection, like a browser tab)."""

    def __init__(self, base: str) -> None:
        url = urllib.parse.urlsplit(base)
        conn_cls = (
            http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
        )
        self.conn = conn_cls(url.netloc, timeout=180)
        self.headers: dict[str, str] = {"User-Agent": "agentops-perf-probe"}

    def call(self, method: str, path: str, body: object | None = None) -> tuple[int, bytes]:
        data = json.dumps(body).encode() if body is not None else None
        headers = dict(self.headers)
        if data is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(2):
            try:
                self.conn.request(method, path, body=data, headers=headers)
                response = self.conn.getresponse()
                return response.status, response.read()
            except (http.client.HTTPException, OSError):
                self.conn.close()  # the server closed an idle connection: reconnect once
                if attempt:
                    raise
        raise AssertionError("unreachable")

    def json(self, method: str, path: str, body: object | None = None) -> object:
        status, raw = self.call(method, path, body)
        if status >= 400:
            raise RuntimeError(f"{method} {path}: HTTP {status} {raw[:200]!r}")
        return json.loads(raw)


def remote_main(base: str, samples: int, runs: int) -> int:
    api = Remote(base.rstrip("/"))
    started = time.perf_counter()
    api.call("GET", "/api/v1/health")
    first_ms = round((time.perf_counter() - started) * 1000)
    token = api.json("POST", "/api/v1/auth/demo", {})["access_token"]  # type: ignore[index]
    api.headers["Authorization"] = f"Bearer {token}"
    page = api.json("GET", "/api/v1/scenarios?limit=50")
    scenario = next(s for s in page["items"] if s["scenario_key"] == "delay_hub_congestion_001")  # type: ignore[index]
    agents = api.json("GET", "/api/v1/agents")
    agent = next(a for a in agents if a["name"] == "rule-based-v1")  # type: ignore[union-attr]
    body = {"scenario_id": scenario["id"], "agent_config_id": agent["id"]}

    latencies: list[float] = []
    run_id = ""
    for _ in range(runs):
        run = api.json("POST", "/api/v1/runs", body)
        run_id = run["id"]  # type: ignore[index]
        while run["status"] in ("queued", "running") or run.get("verdict") is None:  # type: ignore[union-attr]
            time.sleep(1)
            run = api.json("GET", f"/api/v1/runs/{run_id}")
            if run["status"] not in ("queued", "running", "completed"):  # type: ignore[index]
                break
        latencies.append(float(run["latency_ms"] or 0))  # type: ignore[index]
        time.sleep(6)  # stay under the shared demo viewer's 10 runs per minute

    suites = api.json("GET", "/api/v1/suite-runs")
    suite_items = suites["items"] if isinstance(suites, dict) else suites  # type: ignore[index]
    suite_id = next(s["id"] for s in suite_items if s["status"] == "completed")

    def get(path: str) -> Callable[[], object]:
        return lambda: api.call("GET", path)

    results: dict[str, object] = {
        "first_request_ms": first_ms,
        "health": measure(get("/api/v1/health"), samples),
        "list_scenarios_20": measure(get("/api/v1/scenarios"), samples),
        "list_runs_25": measure(get("/api/v1/runs"), samples),
        "get_run": measure(get(f"/api/v1/runs/{run_id}"), samples),
        "get_trace": measure(get(f"/api/v1/runs/{run_id}/trace"), samples),
        "dashboard_summary": measure(get("/api/v1/dashboard/summary"), samples),
        "suite_report_csv": measure(
            get(f"/api/v1/reports/suite-runs/{suite_id}?format=csv"), samples
        ),
        "rule_based_run_server_latency_ms": {
            "p50_ms": round(statistics.median(latencies), 1),
            "max_ms": round(max(latencies), 1),
            "n": len(latencies),
        },
    }
    print(json.dumps(results, indent=2))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--api", help="deployment base URL: measure over HTTPS instead")
    parser.add_argument("--runs", type=int, default=5, help="rule-based runs (--api mode)")
    args = parser.parse_args(argv)
    if args.api:
        return remote_main(args.api, args.samples, args.runs)

    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app
    from app.services.execution.executor import InlineExecutor

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
