# Performance Review — AgentOps Logistics

> System performance, agent efficiency and cost budgets; how to measure them; and a log of periodic
> reviews. **Agent quality** (correctness, safety) is defined in [benchmark.md](benchmark.md) — this file
> covers speed, resource use and cost.
>
> All numbers in §2–§4 are **targets**, not measurements. Measured values go only in §7 with date,
> environment and method. Last updated: 2026-11-07 — nothing measured yet.

---

## 1. Why budgets matter here

- Free-tier backend: one small instance (verify current RAM, historically ~512 MB) that sleeps when idle.
- Free-tier Postgres: limited storage and compute that autosuspends.
- Gemini free tier: per-minute and per-day request limits.
- A portfolio demo must feel responsive once warm, and must never fail because one visitor exhausted the quota.

## 2. Backend and API budgets (warm instance, excluding cold start)

| Operation | Target p95 | Notes |
|---|---|---|
| `GET /health` | ≤ 100 ms | includes `SELECT 1` |
| List endpoints (`/scenarios`, `/runs`, page of 20) | ≤ 300 ms | keyset pagination, indexed filters |
| `GET /runs/{id}` (poll) | ≤ 150 ms | polled every 1.5 s — must stay cheap |
| `GET /runs/{id}/trace` (≤ 100 events) | ≤ 500 ms | single query ordered by `seq`, no N+1 |
| `POST /runs` | ≤ 300 ms | returns 202; execution is async to the request |
| `GET /dashboard/summary` | ≤ 800 ms | aggregate SQL; cache 30 s if needed |
| Export CSV/JSON (31 scenarios) | ≤ 2 s | streamed |
| Cold start (first request after sleep) | **measure only** | documented in README; UI shows waking banner |

## 3. Run and agent budgets

| Item | Target / limit | Enforced? |
|---|---|---|
| Rule-based single run (no injected latency) | ≤ 2 s end-to-end incl. evaluation | target |
| Evaluation + diagnosis per run | ≤ 200 ms | target |
| Gemini single run | p50 target ≤ 20 s; hard timeout 60 s | timeout enforced |
| Agent steps per run | ≤ 8 | enforced |
| Tool calls per run | ≤ 10 | enforced |
| Model calls per LLM run | ≤ 8 (one per step) + 1 repair | enforced via steps |
| Tokens per LLM run | **measure**; budget set after first 10 runs | review item |
| Rule-based 10-scenario suite | ≤ 30 s | target |
| Gemini 10-scenario suite | bounded by `GEMINI_RPM_LIMIT`; measure | throttle enforced |
| Concurrent runs | ≤ 2 | enforced |
| LLM runs per day | ≤ 50 | enforced |

## 4. Resource and cost budgets

| Resource | Budget | How to check |
|---|---|---|
| Backend memory (RSS) | ≤ 400 MB steady state (headroom under ~512 MB) | Render metrics; `psutil` value in `/version` in non-prod |
| DB storage | ≤ 50% of free-tier limit | `SELECT pg_database_size(current_database())` |
| Trace size per run | ≤ 250 KB | `SELECT avg(pg_column_size(t.*)) …` grouped by run |
| Frontend initial JS | ≤ 300 KB gzip | `vite build` output / bundle visualizer |
| Frontend Lighthouse (desktop, warm API) | Performance ≥ 85, Accessibility ≥ 90 | Chrome Lighthouse |
| Trace timeline | smooth with 200 events; virtualise beyond that | manual + React Profiler |
| Infrastructure cost | $0 | provider dashboards |
| Gemini cost | $0 actual (free tier); list-price estimate shown only when usage metadata exists | `usage_json` aggregation |

## 5. How to measure

| What | Method |
|---|---|
| API latency | `scripts/perf_probe.py` (planned): httpx, N = 50 sequential requests per endpoint after a warm-up of 5; reports p50/p95/max as JSON |
| Run latency | from DB: `runs.latency_ms`; suite summaries already compute mean/p95 (p95 only when n ≥ 20) |
| Node/tool timings | `trace_events.duration_ms` grouped by `node_name` / `tool_name` |
| Tokens | `trace_events.usage_json` on `model_response` events; summed per run |
| Query plans | `EXPLAIN (ANALYZE, BUFFERS)` on list, trace and dashboard queries; confirm index use |
| N+1 detection | SQLAlchemy echo / event counter in integration tests: assert query count for trace endpoint ≤ 3 |
| Memory | Render metrics; locally `psutil.Process().memory_info().rss` after a 10-run suite |
| Frontend | `npm run build` size table; Lighthouse; React Profiler for trace viewer |
| Cold start | time from first request to 200 after ≥ 20 min idle, 3 samples |

Always record: date, git SHA, environment (local / Render free / …), dataset size, and N.

## 6. Review cadence and checklist

Run a review at the end of phases **4, 5, 6, 8, 9, 11** and before recording the demo.

Checklist
- [ ] Budgets in §2–§4 re-measured for the endpoints/features touched in the phase
- [ ] No new N+1 queries; new list queries use an index
- [ ] Agent limits (steps, tool calls, timeout) still enforced — tests green
- [x] Token usage per LLM run recorded (from Phase 6; stored in `runs.usage_json` and per turn in the trace)
- [ ] Gemini 429s in the period counted; throttle adjusted if needed
- [ ] DB size and trace growth checked against budget; retention policy applied if > 50%
- [ ] Frontend bundle size checked after adding dependencies
- [ ] Regressions vs previous review explained or fixed
- [ ] Log entry added to §7

## 7. Review log

Template:

```text
### Review <n> — <YYYY-MM-DD> — after Phase <p>
Git SHA:            <sha>
Environment:        <local Docker | Render free + Neon free | …>
Dataset:            <n scenarios, n runs>
Measurements:       <table: metric | target | measured | method | N>
Findings:           <what is over budget / changed>
Actions:            <issues created / fixes made>
```

| # | Date | Phase | Environment | Summary |
|---|---|---|---|---|
| 1 | 2026-11-10 | 4 | local (Windows, Postgres 16.2 portable, in-process client) | All measured API and run budgets met; see Review 1 |
| 2 | 2026-11-12 | 6 | local + Gemini free tier (`gemini-3.5-flash`) | First Gemini runs: ~11 s, ~15k input tokens per run; one slow-provider episode; see Review 2 |

### Review 1 — 2026-11-10 — after Phase 4
Git SHA:            d4611b3 + Phase 4 working tree (committed right after this review)
Environment:        local Windows dev machine, Postgres 16.2 (portable), FastAPI TestClient in-process
                    (excludes network and cold start), `scripts/perf_probe.py`, 3 warm-ups
Dataset:            10 scenarios, 2 agent configs, a few dozen runs

| Measurement | Target (p95) | p50 | p95 | N |
|---|---|---|---|---|
| `GET /health` | ≤ 100 ms | 5.3 ms | 5.9 ms | 20 |
| `GET /scenarios` (page of 20) | ≤ 300 ms | 12.6 ms | 13.7 ms | 20 |
| `GET /runs` (page of 25) | ≤ 300 ms | 11.9 ms | 13.7 ms | 20 |
| `GET /runs/{id}` (poll) | ≤ 150 ms | 10.0 ms | 10.8 ms | 20 |
| `GET /runs/{id}/trace` (13 events) | ≤ 500 ms | 12.6 ms | 14.1 ms | 20 |
| Rule-based run end-to-end, inline (incl. 13 trace writes) | ≤ 2 s | 75.8 ms | 81.1 ms | 20 |

Also observed in the browser on the threaded executor: the carrier-timeout scenario takes ~6.2 s, almost all of it
the scenario's two simulated 3 s carrier timeouts (by design).

Findings:           everything well inside budget; each trace event is its own short transaction, which is fine
                    at this scale. Frontend initial JS 202 KB gzip (budget 300 KB).
Not measured yet:   cold start on Render, Neon latency, memory on the free instance (Phase 11).
Actions:            none needed.

### Review 2 — 2026-11-12 — after Phase 6
Git SHA:            6e1cec0 + Phase 6 working tree (committed right after this review)
Environment:        local Windows dev machine, Postgres 16.2 (portable), uvicorn + threaded executor,
                    Gemini free tier, requested model `gemini-3.5-flash` (served as `gemini-3.6-flash`)
Dataset:            3 real Gemini runs (1 smoke test in memory, 2 from the UI on `policy_refund_demand_001`)

| Measurement | Target | Measured | N |
|---|---|---|---|
| Gemini run wall-clock (completed runs) | p50 ≤ 20 s, hard 90 s (config) | 10.1 s and 12.6 s | 2 |
| Model calls per run | ≤ 8 + 1 repair | 4 and 4 | 2 |
| Input tokens per run | measure | 15,753 and 14,843 (≈ 2.7k on the first call, growing ≈ 1.2k per turn) | 2 |
| Output tokens per run | measure | 389 and 447 | 2 |
| Thinking tokens (minimal level) | measure | not reported (None) | 2 |
| Single Gemini call, normal | — | 1.5–5.2 s (longest = the final `submit_outcome`) | 8 |
| Gemini calls during a slow period | — | 32.6 s and 20.1 s (a 30 s timeout + retry), then a 400 | 1 run |

Findings:           normal runs are well inside budget, and input tokens dominate cost (the whole conversation is
                    resent every turn). During one slow-provider period requests hung until the timeout; the run
                    then sent a 7 s request deadline, which Gemini rejects (minimum 10 s), so it ended `errored`
                    (`provider_bad_request`, infra, not scored against the agent).
Actions:            request timeout lowered to 20 s so a hung request is retried sooner; 10 s floor on every request
                    deadline; no retry unless a full 10 s request still fits before the run deadline; retries now
                    log a warning. Token budget: tentatively ≤ 25k input tokens per run until 10 runs are measured
                    in a Gemini suite (Phase 8).

## 8. Known hotspots and optimisation playbook

| Hotspot | Likely cause | First remedy |
|---|---|---|
| Run status polling load | many open tabs polling | keep `GET /runs/{id}` minimal; back off to 5 s after 30 s; stop on terminal state |
| Slow trace endpoint | large `output_json` blobs | return summaries in list view, full payload on expand |
| Dashboard aggregates | full scans over `runs` | indexes on `(status, created_at)`; cache summary 30 s; materialise per suite run in `summary_json` |
| Gemini latency/429s | free-tier RPM | lower concurrency to 1 for LLM, token-bucket throttle, fewer steps via better prompt |
| Neon wake latency | compute autosuspend | `pool_pre_ping`, short connect timeout + one retry, UI waking banner |
| Memory pressure | heavy imports (LangChain extras) | import only needed integrations; no local embedding models on free instance |
| Bundle size | Monaco editor, Recharts | lazy-load the editor and chart routes |
