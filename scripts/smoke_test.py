"""Smoke-test a deployment (context/deployment.md §8). Standard library only.

Usage:
    python scripts/smoke_test.py --api https://agentops-api.onrender.com \\
        --frontend https://agentops-logistics.vercel.app [--expect-sha 0f1cef9]
    python scripts/smoke_test.py --api ... --after-restart <run_id>   # persisted after a restart
    python scripts/smoke_test.py --api ... --check-login-limit        # locks owner login ~1 min
    python scripts/smoke_test.py --api ... --gemini                   # 1 Gemini run (~4 requests)

--gemini signs in as the owner with OWNER_EMAIL and OWNER_PASSWORD from the environment.
Prints one line per check and exits 1 if any check failed. Waits for a sleeping free-tier
backend to wake up (up to --wake-timeout seconds) before the first check.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any

# Secret *values* (help text may name env vars such as GEMINI_API_KEY; that is fine).
SECRET_PATTERNS = {
    "Google API key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "Postgres URL": re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^\s\"']+@"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\."),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
FOREIGN_ORIGIN = "https://smoke-test.invalid"
FINAL = {"completed", "timed_out", "cancelled", "errored"}

failures: list[str] = []


def report(ok: bool, name: str, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f": {detail}" if detail else ""))
    if not ok:
        failures.append(name)
    return ok


def request(
    method: str,
    url: str,
    body: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
) -> tuple[int, dict[str, str], bytes]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=dict(headers or {}))
    if data is not None:
        req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "agentops-smoke-test")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return 0, {}, b""  # unreachable (or still waking up)


def get_json(url: str, token: str | None = None) -> tuple[int, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    status, _, raw = request("GET", url, headers=headers)
    try:
        return status, json.loads(raw or b"null")
    except json.JSONDecodeError:
        return status, None


def post_json(url: str, body: Any, token: str | None = None, **kw: Any) -> tuple[int, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    headers.update(kw.pop("headers", {}))
    status, _, raw = request("POST", url, body, headers=headers, **kw)
    try:
        return status, json.loads(raw or b"null")
    except json.JSONDecodeError:
        return status, None


def wait_awake(api: str, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    started = time.monotonic()
    while True:
        try:
            status, body = get_json(f"{api}/api/v1/health")
            if status == 200:
                waited = time.monotonic() - started
                return report(
                    body.get("status") == "ok" and body.get("db") == "ok",
                    "health",
                    f"{body} (answered after {waited:.0f} s)",
                )
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        if time.monotonic() > deadline:
            return report(False, "health", f"no healthy answer within {timeout_s:.0f} s")
        time.sleep(5)


def pick(api: str, token: str, agent_name: str) -> tuple[str | None, str | None]:
    _, agents = get_json(f"{api}/api/v1/agents", token)
    agent = next((a for a in agents or [] if a["name"] == agent_name), None)
    _, page = get_json(f"{api}/api/v1/scenarios?q=delay_weather_hold_001&limit=5", token)
    scenario = next(
        (s for s in (page or {}).get("items", []) if s["scenario_key"] == "delay_weather_hold_001"),
        None,
    )
    return (scenario or {}).get("id"), (agent or {}).get("id")


def run_one(api: str, token: str, agent_name: str, timeout_s: float) -> dict[str, Any] | None:
    scenario_id, agent_id = pick(api, token, agent_name)
    if not report(bool(scenario_id and agent_id), f"find scenario and {agent_name}"):
        return None
    status, run = post_json(
        f"{api}/api/v1/runs", {"scenario_id": scenario_id, "agent_config_id": agent_id}, token
    )
    if not report(status == 202, f"launch {agent_name} run", f"HTTP {status} {run}"):
        return None
    deadline = time.monotonic() + timeout_s
    # A completed run is scored a moment later: wait for the verdict too.
    while (
        run["status"] not in FINAL or (run["status"] == "completed" and run.get("verdict") is None)
    ) and time.monotonic() < deadline:
        time.sleep(2)
        _, run = get_json(f"{api}/api/v1/runs/{run['id']}", token)
    return run


def check_run_persisted(api: str, token: str, run_id: str, label: str) -> None:
    status, run = get_json(f"{api}/api/v1/runs/{run_id}", token)
    report(status == 200, f"{label}: run found", f"HTTP {status}")
    if status != 200:
        return
    report(
        run["status"] == "completed" and run.get("verdict") is not None,
        f"{label}: status and score",
        f"{run['status']}, {run.get('verdict')} {run.get('score')}",
    )
    _, trace = get_json(f"{api}/api/v1/runs/{run_id}/trace", token)
    events = (trace or {}).get("events", [])
    report(len(events) > 0, f"{label}: trace", f"{len(events)} events")


def check_cors(api: str, frontend: str | None) -> None:
    def preflight(origin: str) -> str | None:
        _, headers, _ = request(
            "OPTIONS",
            f"{api}/api/v1/scenarios",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        return headers.get("access-control-allow-origin")

    foreign = preflight(FOREIGN_ORIGIN)
    report(foreign is None, "CORS rejects a foreign origin", f"allow-origin={foreign}")
    if frontend:
        allowed = preflight(frontend)
        report(allowed == frontend, "CORS allows the frontend", f"allow-origin={allowed}")


def check_frontend(frontend: str) -> None:
    status, _, html = request("GET", frontend)
    report(status == 200 and b'<div id="root">' in html, "frontend loads", f"HTTP {status}")
    status, _, deep = request("GET", f"{frontend}/runs")
    report(status == 200 and b'<div id="root">' in deep, "frontend deep link (SPA rewrite)")
    assets = sorted(set(re.findall(rb'(?:src|href)="(/assets/[^"]+\.(?:js|css))"', html)))
    report(bool(assets), "frontend assets listed", f"{len(assets)} files")
    found: list[str] = []
    total = 0
    for path in assets:
        _, _, body = request("GET", frontend + path.decode())
        total += len(body)
        text = body.decode("utf-8", errors="replace")
        found += [
            f"{name} in {path.decode()}" for name, rx in SECRET_PATTERNS.items() if rx.search(text)
        ]
    detail = "; ".join(found) or f"{total} bytes scanned"
    report(not found, "no secrets in the frontend bundle", detail)


def check_login_limit(api: str) -> None:
    codes = []
    for i in range(11):
        status, _ = post_json(
            f"{api}/api/v1/auth/login",
            {"email": "smoke-test@example.invalid", "password": "not-the-password"},
            headers={"X-Forwarded-For": f"10.255.0.{i}"},  # a spoofed address that changes
        )
        codes.append(status)
    report(
        codes[:10] == [401] * 10 and codes[-1] == 429,
        "login limit ignores a spoofed X-Forwarded-For",
        f"codes {codes}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test an AgentOps deployment")
    parser.add_argument("--api", required=True, help="backend base URL, no trailing /api/v1")
    parser.add_argument("--frontend", help="frontend URL (enables CORS-allow and bundle checks)")
    parser.add_argument("--expect-sha", help="git SHA (prefix) the backend should report")
    parser.add_argument("--min-scenarios", type=int, default=31)
    parser.add_argument("--wake-timeout", type=float, default=150)
    parser.add_argument("--run-timeout", type=float, default=120)
    parser.add_argument("--after-restart", metavar="RUN_ID", help="only check this run persisted")
    parser.add_argument("--check-login-limit", action="store_true")
    parser.add_argument("--gemini", action="store_true", help="also launch one Gemini run")
    args = parser.parse_args()
    api = args.api.rstrip("/")
    frontend = args.frontend.rstrip("/") if args.frontend else None

    if not wait_awake(api, args.wake_timeout):
        return 1
    status, version = get_json(f"{api}/api/v1/version")
    sha = (version or {}).get("git_sha", "")
    if args.expect_sha:
        report(sha.startswith(args.expect_sha), "version", f"git_sha {sha}")
    else:
        report(status == 200, "version", f"{version}")

    status, token_body = post_json(f"{api}/api/v1/auth/demo", {})
    if not report(status == 200, "demo login", f"HTTP {status}"):
        return 1
    token = token_body["access_token"]

    if args.after_restart:
        check_run_persisted(api, token, args.after_restart, "after restart")
        return 1 if failures else 0

    _, page = get_json(f"{api}/api/v1/scenarios?limit=1", token)
    total = (page or {}).get("total", 0)
    report(total >= args.min_scenarios, "scenarios seeded", f"{total} scenarios")

    run = run_one(api, token, "rule-based-v1", args.run_timeout)
    if run is not None:
        report(
            run["status"] == "completed" and run.get("verdict") == "PASS",
            "rule-based-v1 run end to end",
            f"{run['id']}: {run['status']}, {run.get('verdict')} {run.get('score')}, "
            f"{run.get('latency_ms')} ms",
        )
        check_run_persisted(api, token, run["id"], "rule-based-v1 run")
        print(f"RUN_ID={run['id']}")  # for a later --after-restart check

    check_cors(api, frontend)
    if frontend:
        check_frontend(frontend)
    if args.check_login_limit:
        check_login_limit(api)

    if args.gemini:
        email, password = os.environ.get("OWNER_EMAIL"), os.environ.get("OWNER_PASSWORD")
        if report(bool(email and password), "owner credentials in the environment"):
            status, body = post_json(
                f"{api}/api/v1/auth/login", {"email": email, "password": password}
            )
            if report(status == 200, "owner login", f"HTTP {status}"):
                owner = body["access_token"]
                gem = run_one(api, owner, "gemini-flash-v1", max(args.run_timeout, 240))
                if gem is not None:
                    error = (gem.get("error") or {}).get("code")
                    report(
                        gem["status"] in FINAL,
                        "gemini-flash-v1 run finished",
                        f"{gem['id']}: {gem['status']}, {gem.get('verdict')} {gem.get('score')}"
                        + (f", error {error}" if error else ""),
                    )

    print(f"\n{'All checks passed' if not failures else f'{len(failures)} check(s) failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
