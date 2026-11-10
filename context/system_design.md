# System Design — AgentOps Logistics

> High-level design: **what** the system does, **why** it is shaped this way, and how it behaves under
> failure. Concrete modules, schemas and interfaces live in [architecture.md](architecture.md).
> Source of truth for product scope: [../PROJECT.md](../PROJECT.md). Requirements: [../requirement.md](../requirement.md).
>
> Last updated: 2026-11-07 (planning; nothing implemented yet).

---

## 1. Goals and non-goals

**Goals**
1. Reproducibly test a logistics CX agent against versioned scenarios with hidden ground truth.
2. Make every score explainable: each point gained or lost traces back to an assertion and a trace event.
3. Make safety failures impossible to hide behind a good aggregate score.
4. Detect regressions between agent versions on identical scenario versions.
5. Run end-to-end on free tiers, and run fully **without** any LLM (rule-based agents) for CI and public demo.

**Non-goals** — see PROJECT.md §3.2. Notably: no real integrations, no multi-tenancy, no worker cluster in the MVP.

## 2. System context

```text
                ┌──────────────┐        ┌──────────────────────────┐
  Owner ───────▶│              │ HTTPS  │  FastAPI backend          │──── Gemini API (server-side key,
  Demo viewer ─▶│  React SPA   │──JSON─▶│  (API + in-process runner)│     owner-only, daily-capped)
                │  (Vercel)    │◀───────│  (Render)                 │
                └──────────────┘ poll   └────────────┬─────────────┘
                                                     │ SQL (TLS)
                                              ┌──────▼──────┐
                                              │ PostgreSQL  │  scenarios, configs, runs,
                                              │ (Neon)      │  traces, evaluations, reports
                                              └─────────────┘
```

No external system other than the model API is ever called. All "logistics systems" are mock tools reading
scenario-local seeded data.

## 3. Core concepts (glossary)

| Concept | Meaning |
|---|---|
| **Scenario** | A logical test case identified by `scenario_key` (e.g. `delay_hub_congestion_001`) |
| **Scenario version** | An immutable snapshot (`scenario_key`, `version`) once used in a run. Runs reference versions, never the mutable "latest" |
| **Visible input** | `customer_message` + `visible_context` + permitted tool descriptions. The only thing the agent sees up front |
| **Mock data** | Scenario-local records (shipments, events, carrier status, tickets) that tools read from. Agent sees them only through tool calls |
| **Ground truth** | Expected root cause, required evidence IDs, required/forbidden actions, escalation expectation, response constraints. Backend-only |
| **Evidence ID** | Stable ID on every mock record and SOP section, e.g. `event:SHP-1042:07`, `sop:delay-comm#s3` (see [benchmark.md §3](benchmark.md)) |
| **Agent config** | Versioned, immutable-once-used definition of an agent: provider, model, prompt, tools, limits |
| **Run** | One execution of one agent config on one scenario version |
| **Suite / suite run** | A named set of scenarios / one execution of a config across that set |
| **Trace event** | One observable step in a run (node enter/exit, model call, tool call, tool result, error, final outcome). Referenced as `te:<seq>` |
| **Assertion** | One deterministic check with id, pass/fail, expected, actual and cited trace events |
| **Verdict** | Run-level evaluation outcome: `PASS`, `FAIL`, `FAILED_POLICY`, `ERROR` |
| **Failure report** | Diagnosis entries derived from failed assertions, each citing evidence |

## 4. Key design decisions

Each decision is final unless revisited explicitly; record changes here.

| # | Decision | Rationale | Consequence |
|---|---|---|---|
| D-01 | **Modular monolith** (one FastAPI service) | Free-tier hosting gives one small instance; spec forbids microservices | Clear internal module boundaries so a worker can be split out later |
| D-02 | **In-process background runner** (thread pool) behind a `RunExecutor` interface, bounded by `MAX_CONCURRENT_RUNS` | Runs are short (seconds to ~1 min); Redis/Celery would need another paid/free service | Runs die if the instance restarts → startup sweeper marks orphans (D-10) |
| D-03 | **Sync SQLAlchemy 2 + psycopg 3**; DB work in threadpool | Simpler and less error-prone than mixing async sessions; load is tiny | Route handlers are `def` where they touch the DB; agent runner runs in a worker thread |
| D-04 | **Ground truth never leaves the backend evaluator path**; agent input built by a single `build_agent_input()` function | One choke point is easy to test for leakage | Leakage test asserts serialized agent input contains none of the ground-truth values |
| D-05 | **Rule-based agents first**, implemented as the same LangGraph graph with a deterministic "decider" instead of an LLM | Proves platform end-to-end at zero cost; gives CI a real agent; gives public demo a free agent | Two profiles (`rule-based-v1` good, `rule-based-v2-flawed`) produce a real, honest regression comparison |
| D-06 | **One closed global root-cause enum** (independent of category) | Free-text root causes can't be exact-matched; a per-category list would hint the category | Agent is given the whole label list — it reveals no answer; see [benchmark.md §2.2](benchmark.md) |
| D-07 | **Stable evidence IDs on all data**; citations must have been actually returned by a tool in the same run | Makes evidence scoring deterministic and catches fabricated citations | Mock data authors must assign IDs; validator enforces uniqueness |
| D-08 | **Policy enforced in the tool layer**; forbidden attempts are recorded *and* blocked | Prompts are not a security boundary | An attempted forbidden call fails the safety gate even though it had no effect |
| D-09 | **Escalation truth = `request_escalation` tool call**; outcome flag mismatch is its own failed assertion | Two signals can disagree; the action is what matters operationally | `escalation_flag_consistent` assertion |
| D-10 | **Startup sweeper** marks `queued`/`running` runs older than start time as `errored(orphaned)` | Free instances sleep/restart and kill in-flight runs | No run stays "running" forever |
| D-11 | **Thought parts discarded at the provider adapter** | Spec forbids storing chain-of-thought; Gemini may return thought summaries | Trace stores only tool calls, visible messages, structured outcome |
| D-12 | **Structured outcome via a terminal `submit_outcome` tool** | Combining free tool-calling with a JSON response schema is fragile across models; a tool with a Pydantic schema is uniform | Malformed outcome → one repair retry → `agent_error(malformed_output)` |
| D-13 | **Deterministic checks first; LLM judge optional, tone/clarity only** | Auditable, free, CI-friendly | When judge is off, its weight is redistributed proportionally |
| D-14 | **JWT bearer tokens** (not cookies) | Frontend (Vercel) and backend (Render) are on different sites; third-party cookies are unreliable | Token kept in memory + `sessionStorage`; short expiry |
| D-15 | **Lexical SOP search (Postgres full-text) in MVP; pgvector later** | Works with zero embedding cost; Neon supports pgvector when needed | Retrieval interface hides which backend is used |
| D-16 | **Daily LLM run cap + global concurrency limit** stored/enforced server-side | Protects free Gemini quota from public visitors | Viewers only get rule-based agents; owner gets capped Gemini runs |

## 5. Key flows

### 5.1 Single run

```text
Client            API                RunService          Executor(thread)        Agent graph / Tools        Evaluator/Diagnosis
  │ POST /runs      │                    │                     │                        │                          │
  │────────────────▶│ validate, authz,   │                     │                        │                          │
  │                 │ check caps ───────▶│ create Run(queued)  │                        │                          │
  │◀── 202 {run_id} │                    │ snapshot scenario   │                        │                          │
  │                 │                    │ version + config ──▶│ status=running         │                          │
  │ GET /runs/{id}  │                    │                     │ build_agent_input() ──▶│ loop: decide → tool call │
  │ (poll 1–2 s)    │                    │                     │                        │  policy check → mock data│
  │                 │                    │                     │◀── trace events (each persisted immediately)      │
  │                 │                    │                     │ outcome / error / timeout                         │
  │                 │                    │                     │──────────────────────────────────────────────────▶│ assertions,
  │                 │                    │                     │                                                   │ score, verdict,
  │                 │                    │                     │◀──────────────────────────────────────────────────│ failure report
  │                 │                    │                     │ status=completed|errored|timed_out               │
  │◀── status+score │                    │                     │                                                   │
```

Notes:
- Trace events are written as they happen (not batched at the end), so a crashed run still has a partial trace.
- Evaluation runs even for `errored`/`timed_out` runs when the error is agent-attributable (it yields `agent_crash`/`timeout` failures). Infrastructure errors (quota, DB) skip evaluation and are excluded from metrics.

### 5.2 Suite run
1. `POST /suites/{id}/runs` → `SuiteRun(queued)` + one `Run(queued)` per scenario (pinned versions).
2. Executor drains runs respecting the global concurrency limit (default 2) and, for Gemini, a per-minute throttle.
3. When all child runs are terminal, compute `summary_json` (metrics from [benchmark.md §9](benchmark.md)) and mark suite run `completed`.

### 5.3 Regression comparison
`GET /comparisons?baseline_suite_run_id=A&candidate_suite_run_id=B` → pair runs by (`scenario_key`, `version`); classify each pair: `fixed`, `newly_failed`, `still_failing`, `still_passing`, `safety_regression` (candidate has a gate failure baseline did not), `not_comparable`; compute metric deltas. Pure function over persisted data — never reruns anything.

### 5.4 Scenario edit / versioning
- Edit on a version **not yet used** in any run → update in place.
- Edit on a **used** version → insert `version + 1`; old row untouched. Same rule for agent configs.
- Archive = `status = archived`; never hard-delete versions referenced by runs.

### 5.5 Auth
- `POST /auth/login` (owner email+password) → JWT `{sub, role: owner}`.
- `POST /auth/demo` → JWT `{role: viewer}`, no password.
- Dependency `require_role("owner")` on every write endpoint; viewer may only `POST /runs` with a `rule_based` config.

## 6. Ground-truth isolation

| Data | Agent input | Tools return | Evaluator | Owner UI | Viewer UI |
|---|---|---|---|---|---|
| customer_message, visible_context | ✅ | — | ✅ | ✅ | ✅ |
| mock_data records | ❌ (only via tools) | ✅ (scoped to scenario) | ✅ | ✅ | ✅ |
| permitted tool descriptions | ✅ | — | ✅ | ✅ | ✅ |
| global root-cause label list | ✅ | — | ✅ | ✅ | ✅ |
| ground_truth, evaluation weights, rubric | ❌ | ❌ | ✅ | ✅ | ❌ |

Enforcement: (1) `build_agent_input()` is the only constructor of agent input; (2) tools receive a `ScenarioDataView` that structurally lacks ground truth; (3) leakage test per scenario; (4) API serializers for viewers exclude `ground_truth`.

## 7. Run lifecycle

```text
          ┌────────┐  executor picks   ┌─────────┐  outcome submitted  ┌───────────┐
create ──▶│ queued │──────────────────▶│ running │────────────────────▶│ completed │──▶ verdict PASS/FAIL/FAILED_POLICY
          └───┬────┘                   └──┬──┬───┘                     └───────────┘
              │ cancel                    │  │ wall-clock limit        ┌───────────┐
              ▼                           │  └────────────────────────▶│ timed_out │──▶ verdict FAIL (timeout)
          ┌───────────┐  cancel           │                            └───────────┘
          │ cancelled │◀──────────────────┤ exception / crash          ┌─────────┐
          └───────────┘                   └───────────────────────────▶│ errored │──▶ agent error → FAIL (agent_crash)
                                                                       └─────────┘    infra error → ERROR (excluded)
```

`status` = execution state; `verdict` = evaluation outcome. They are separate columns.

## 8. Limits and concurrency (defaults, all configurable)

| Limit | Default | Where enforced |
|---|---|---|
| Max concurrent runs (global) | 2 | executor semaphore |
| Max agent steps (graph iterations) | 8 | graph recursion limit + counter |
| Max tool calls per run | 10 | tool gateway |
| Max model retries (transient) | 2, exponential backoff 1 s → 4 s | provider adapter |
| Run wall-clock timeout | 60 s (LLM) / 10 s (rule-based) | executor |
| Daily LLM-backed runs | 50 | `usage_counters` table, checked at run creation |
| Gemini request throttle | configurable RPM (set below current free-tier limit) | provider adapter token bucket |
| Request body | 1 MB | `BodySizeLimitMiddleware` (413) |
| Run creation rate | 10/min per principal | run service (429) |
| Queued + running runs | 20 | run service (429 `run_queue_full`) |
| Watchdog | `timeout_s` + 15 s grace | executor timer marks the run `timed_out` |

## 9. Failure modes and handling

| Failure | Detection | Handling | Run outcome |
|---|---|---|---|
| Gemini 429 / quota exhausted | HTTP 429 / `RESOURCE_EXHAUSTED` | backoff ×2, then stop | `errored(provider_quota)`, verdict `ERROR` (excluded, infra) |
| Gemini 5xx / network | status/exception | backoff ×2 | `errored(provider_unavailable)`, `ERROR` |
| Malformed `submit_outcome` args | Pydantic validation | one repair prompt | then `errored(malformed_output)` → `FAIL` (agent) |
| Agent loops | step/tool-call counter | stop graph | `completed` with `limit_exceeded` assertion failed → `FAIL` |
| Wall-clock exceeded | executor timer | cancel token, stop | `timed_out` → `FAIL(timeout)` |
| Mock tool simulated error (scenario-designed) | tool returns typed error | passed to agent as tool result | agent must handle; may yield `tool_failure_unhandled` |
| Invalid tool args | Pydantic | typed `invalid_arguments` error to agent; recorded | assertion `tool_args_valid` fails |
| Forbidden tool attempted | policy engine | blocked, typed `policy_denied` error to agent; recorded | safety gate → `FAILED_POLICY` |
| DB unreachable (Neon suspended) | connection error | `pool_pre_ping`, retry once | API 503 `db_unavailable`; run `errored(infra)` |
| Instance restart mid-run | startup sweeper | mark orphaned | `errored(orphaned)`, `ERROR` |
| Backend cold start | frontend request timeout | UI shows "waking up backend…" and retries | — |

## 10. Security model

- **Secrets:** env vars only (`GEMINI_API_KEY`, `JWT_SECRET`, `DATABASE_URL`). Settings object marks them `SecretStr`; logging filter redacts known secret patterns.
- **AuthZ:** two roles; role checked in a FastAPI dependency, never in the frontend alone.
- **Prompt injection:** system prompt states that customer messages, tool results and SOP text are untrusted data; more importantly, consequential tools are policy-gated server-side, so an injected instruction can at most cause a *recorded, blocked attempt*. Dedicated injection scenarios test this ([benchmark.md](benchmark.md)).
- **PII:** data is synthetic, but redaction (names, phones, emails, street addresses) is applied when traces/reports are serialized for display/export, to demonstrate the practice.
- **CORS:** explicit allowlist; no wildcard with credentials.
- **Input limits:** body size, pagination caps (`limit ≤ 100`), JSON-schema validation on scenario import.

## 11. Capacity estimate (sanity check for free tiers)

| Item | Estimate |
|---|---|
| Scenario JSON | 5–30 KB each → 30 scenarios × 3 versions ≈ < 3 MB |
| Trace events per run | ~15–60 rows, ~1–4 KB each → ≤ 250 KB/run |
| Runs | 1,000 runs ≈ ≤ 250 MB worst case; typical far less |
| Neon free storage | small (verify current limit, historically ~0.5 GB) → add trace retention: prune raw tool outputs of non-seeded runs older than 30 days if needed |
| Gemini calls per LLM run | ~3–8 model calls (one per graph step) |

## 12. Trade-offs and known limitations

- In-process execution loses in-flight runs on restart (accepted; sweeper makes it visible).
- Polling (1–2 s) instead of SSE/WebSockets: simpler, fine at this scale.
- Rule-based agents are scripted heuristics, not "intelligent"; they exist to validate the platform and give a free demo, and are labelled as such.
- LLM non-determinism: a single run per scenario can be noisy; repeats (FR-08.5) mitigate.
- Deterministic response checks (keywords/regex) can miss paraphrases; documented per constraint in [benchmark.md §8](benchmark.md).

## 13. Evolution path

1. Split executor into a worker process with a Postgres-backed job queue (`SELECT … FOR UPDATE SKIP LOCKED`) — no Redis needed.
2. SSE for live trace streaming.
3. Embedding retrieval with pgvector.
4. Multi-workspace via the already-present `workspace_id` columns.
5. OpenTelemetry export of trace events.
