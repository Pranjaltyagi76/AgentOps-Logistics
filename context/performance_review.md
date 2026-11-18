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
| LLM runs per day | ≤ 4 (free tier: ~20 Gemini requests/day) | enforced |

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
- [x] Frontend bundle size checked after adding dependencies (2026-11-16, Phase 9: initial JS 214.6 KB gzip,
  ScenarioEditor chunk 139.7 KB loaded on demand)
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
| 3 | 2026-11-12 | 8 | local + Gemini free tier | Rule-based suites in 3–7 s; Gemini suite blocked by overload and a 20-requests-per-day free quota; see Review 3 |
| 4 | 2026-11-16 | 8 (follow-up) | local + Gemini free tier | `llm-4` Gemini suite: calls took 15–39 s, all 4 runs failed on provider timeouts; see Review 4 |
| 5 | 2026-11-16 → 18 | 11–12 | **production**: Render free (Docker, 0.1 CPU, Singapore) + Neon free (Singapore), client in India | API p95 106–142 ms incl. ~95 ms network; cold start 58–63 s; run p50 314 ms; Lighthouse 100/100/100; see Review 5 |

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

### Review 3 — 2026-11-12 — after Phase 8
Git SHA:            7bf3677 + Phase 8 commits
Environment:        local Windows dev machine, Postgres 16.2 (portable), uvicorn + threaded executor
                    (2 rule-based workers + 1 LLM worker), Gemini free tier
Dataset:            suite `mvp-10` (10 scenarios), 3 suite runs

| Measurement | Target | Measured | N |
|---|---|---|---|
| Rule-based 10-scenario suite, wall clock | ≤ 30 s | 6.7 s (v1), 3.4 s (v2) | 1 each |
| Rule-based run latency in a suite | — | mean 0.71 s (v1; the carrier-timeout scenario's two simulated 3 s timeouts dominate), 0.39 s (v2) | 10 |
| Gemini 10-scenario suite | bounded by `GEMINI_RPM_LIMIT`; measure | 320 s until all 10 runs ended — every run a platform error | 1 |
| Throttle wait per Gemini run | — | up to 37.6 s, excluded from the agent's time limit (runs kept their full 90 s) | 7 |

Findings:           The Gemini **free tier allows 20 generate requests per day** for `gemini-3.5-flash` (served as
                    `gemini-3.6-flash`; Google's 429 names the metric `generate_content_free_tier_requests, limit: 20`).
                    Smoke tests, browser runs, judge calls and retries earlier in the day had used it, and the model
                    was also overloaded (503 "high demand", 504 deadline). `LLM_DAILY_RUN_CAP=50` is far above what
                    the free tier can serve (~4 requests per run ⇒ ~5 runs per day).
Actions:            daily-quota 429s are no longer retried. `LLM_DAILY_RUN_CAP` default lowered 50 → 4
                    (2026-11-16), so a Gemini suite now needs ≤ 4 scenarios per day; use a model or tier with a
                    higher daily limit for the full MVP suite. No Gemini suite metrics exist yet.

### Review 4 — 2026-11-16 — Gemini `llm-4` suite
Suite runs `8537de92` (rule-based-v1, 4/4 PASS, 6.3 s) and `5b03ee9a` (gemini-flash-v1, 369 s, no usable result).

| Measurement | 2026-11-12 | 2026-11-16 |
|---|---|---|
| Gemini call latency (agent turns) | 1.5–5.2 s | 14.9–39.0 s |
| Runs finished by the agent | 2 of 2 | 0 of 4 (3 × 504 deadline, 1 × read timeout) |
| Input tokens per run (mean, where reported) | ~15k | 6.9k (runs stopped early) |

Findings:           at 15–40 s per call, a 4-step Gemini run cannot fit the 20 s request timeout and 90 s run limit;
                    the free tier's latency varies by an order of magnitude between days. The SDK raises timeouts
                    from its own httpx fork (`httpx2`), which the adapter missed, so one timeout was scored as an
                    agent failure.
Actions:            `httpx2` timeouts and transport errors now map to `provider_unavailable` (tested). Not changed:
                    the time limits (raising them would make slow-provider days look like slow agents). Gemini
                    benchmark results stay pending until a day with normal latency; check the Settings page for
                    remaining quota before launching.

### Review 5 — 2026-11-16 to 2026-11-18 — production (Phases 11–12)
Git SHA:            fd2be21 (API figures, 2026-11-18), 02660c8 (frontend)
Environment:        Render free web service (Docker, 0.1 CPU, 512 MB, Singapore) + Neon free Postgres 16
                    (Singapore); client: Windows laptop in India over home broadband. Frontend on Vercel Hobby.
Dataset:            31 scenarios, ~95 runs (20 labelled demo runs, 2 suite runs of 31, smoke and probe runs)
Method:             `python scripts/perf_probe.py --api <url> --samples 20 --runs 5` (one kept-alive HTTPS
                    connection, client-side timings, so every figure includes the network round trip, roughly
                    the health p50 of ~97 ms; run latency
                    is the server-recorded `latency_ms`); cold start = first `/health` after ≥ 15 min idle
                    (curl); Lighthouse 12 desktop preset on the production build served locally (the live site
                    sits behind Vercel's bot checkpoint, which headless browsers hit).

| Metric | Target | Measured | Status |
|---|---|---|---|
| `GET /health` p95 | ≤ 100 ms | 113.5 ms end to end (p50 96.7 ms) | the budget is server-side; end to end it is over by ~14 ms, almost all of it the India → Singapore round trip (no server timing was recorded) |
| List scenarios / runs p95 | ≤ 300 ms | 115.3 / 106.1 ms | met |
| `GET /runs/{id}` p95 (poll) | ≤ 150 ms | 137.5 ms | met |
| `GET /runs/{id}/trace` p95 | ≤ 500 ms | 130.9 ms | met |
| `GET /dashboard/summary` p95 | ≤ 800 ms | 141.8 ms | met |
| Suite report CSV (31 runs) p95 | ≤ 2 s | 1.33 s (p50 0.94 s) | met |
| Rule-based single run | ≤ 2 s | p50 314 ms, max 521 ms (n = 5); full-31 suite mean 0.84 s, p95 1.40 s | met |
| Rule-based 31-run suite | ≤ 30 s (for 10) | finished in under a minute on 0.1 CPU (2 at a time) | met (scaled) |
| Cold start | measure only | 63 s (seeding before the server) → 58 s (seeding in the background); Render's own wake is ~50 s | measured |
| Backend memory | ≤ 400 MB | not available (Render shows no metrics on the free plan); no restarts or OOM events during deploys and a 31-run suite | not measured |
| Frontend initial JS | ≤ 300 KB gzip | 215.1 KB | met |
| Lighthouse desktop (login page) | perf ≥ 85, a11y ≥ 90 | 100 / 100 / 100 (perf, a11y, best practices); FCP = LCP = 0.5 s, TBT 0 ms, CLS 0 | met |
| DB storage, trace size per run | ≤ 50 % of free tier; ≤ 250 KB | DB_SIZE_PENDING | DB_STATUS_PENDING |

Findings:           every warm API budget is met; end to end, distance (India → Singapore) dominates. Cold starts are
                    dominated by the free instance's own wake-up; moving seeding behind the server start saved ~5 s.
                    Production runs are ~3× slower than locally (0.1 CPU) and still far inside budget.
Actions:            seeding moved to the background (Phase 11); the waking banner covers the minute; no keep-alive
                    pinging (deployment.md §5). Memory stays unmeasured until a paid plan or an in-app RSS readout.

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
