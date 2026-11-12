# Phase-wise Roadmap — AgentOps Logistics

> Build in vertical slices; **every phase leaves the app runnable**. Rules from PROJECT.md §24 apply:
> at the start of each phase state the phase, files to change and acceptance criteria; get approval;
> implement only that phase; add tests; report files changed, commands, test results, limitations, next phase.
>
> **Change from PROJECT.md §22 (agreed 2026-11-07):** the baseline LangGraph agent is built first with a
> **rule-based (no-LLM) decider**; the Gemini decider becomes its own phase after the evaluator works.
> This makes the whole pipeline — and a real regression comparison — work without spending LLM quota.
> Phase numbers below therefore differ from PROJECT.md; the mapping is in the last column.

## Status overview

| Phase | Name | Status | PROJECT.md phase |
|---|---|---|---|
| 0 | Foundation | ✅ done (CI green incl. real Postgres; local Docker DB pending) | 0 |
| 1 | Scenario system + auth | ✅ done (2026-11-08) | 1 |
| 2 | Mock logistics tools, policy, SOP search | ✅ done (2026-11-09) | 2 (+ lexical part of 9) |
| 3 | Agent graph + rule-based agents + agent configs | ✅ done (2026-11-09) | 3 (first half) |
| 4 | Execution and trace | ✅ done (2026-11-10) | 4 |
| 5 | Deterministic evaluator | ✅ done (2026-11-10) | 5 |
| 6 | Gemini LLM agent | ✅ done (2026-11-12) | 3 (second half) |
| 7 | Failure diagnosis (+ optional judge) | ⬜ | 6 |
| 8 | Benchmark suites and regression | ⬜ | 7 |
| 9 | Dashboard and reports | ⬜ | 8 |
| 10 | RAG and expanded scenarios (30+) | ⬜ | 9 |
| 11 | Deployment | ⬜ | 10 |
| 12 | Portfolio polish | ⬜ | 11 |

Legend: ⬜ not started · 🟨 in progress · ✅ done (acceptance verified). Update this table at the end of every phase.

---

## Phase 0 — Foundation

**Goal:** empty but runnable full stack with DB connectivity and CI.

Tasks
- `git init`, `.gitignore` (Python, Node, `.env`, `.venv`, `dist`), `.env.example` in `backend/` and `frontend/`.
- `docker-compose.yml` with `pgvector/pgvector:pg16` (named volume, healthcheck, port 5432).
- `backend/`: `pyproject.toml` (pinned deps, ruff config, pytest config), `app/main.py` app factory,
  `core/config.py` Settings, `core/logging.py`, `core/errors.py` error envelope, `db/session.py`,
  Alembic init + empty baseline migration, `api/v1/health.py` (`/health` checks DB with `SELECT 1`, `/version`).
- `frontend/`: Vite React TS, Tailwind, shadcn/ui init, React Router, TanStack Query, axios instance using
  `VITE_API_BASE_URL`, `AppShell` with sidebar placeholders, a status page calling `/health`.
- `.github/workflows/ci.yml`: backend (ruff, migrations, pytest with Postgres service container) + frontend (oxlint, tsc, vitest, build).
- README "Getting started" made real.

Acceptance
- [ ] `docker compose up -d db` healthy (or Neon dev branch): **pending**, as Docker isn't installed on the dev machine yet
- [x] `uvicorn app.main:app` serves `/api/v1/health`; DB down → 503 with envelope (verified locally 2026-11-08)
- [x] `/api/v1/health` → `{"status":"ok","db":"ok"}` against real Postgres: `db`-marked test passed in CI (PR #1, 2026-11-08), migration 0001 applied
- [x] `npm run dev` status page shows backend status; DB shows "Unavailable" without Postgres (verified in browser)
- [ ] Status page shows DB green: needs a local Postgres
- [x] `ruff check`, `ruff format --check`, `pytest`, `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` pass locally
- [x] Same checks pass in GitHub Actions (PR #1: backend 11 passed / 0 skipped, frontend all green)

Tests: health OK, health DB-down, real-DB health (CI), version, settings from env, migration URL fallback,
request-ID echo/replace, 404 envelope, CORS allowlist, secret redaction; frontend status page OK / DB down / API unreachable.

Implementation notes: Python deps use **uv** (`uv.lock`); the frontend linter is **oxlint** (Vite template default);
TypeScript 7, Vite 8, React 19, React Router 8, Tailwind 4, shadcn/ui (radix-nova preset).

---

## Phase 1 — Scenario system + auth

**Goal:** validated, versioned scenarios stored in Postgres and browsable in the UI.

Tasks
- `domain/taxonomy.py`: categories, root-cause enums, tool names, failure types ([benchmark.md §2](benchmark.md)).
- `schemas/scenario.py`: `ScenarioSpec` Pydantic model with validators — enum root cause, unique evidence IDs,
  `required_evidence` ⊆ declared IDs, forbidden/required actions ∈ tool registry names, forbidden tools present in `available_tools`, weights sum to 100.
- Models + migration: `users`, `workspaces`, `scenarios`.
- Auth: owner login (argon2/bcrypt + JWT), demo login, `require_role`; `scripts/create_owner.py`.
- 10 MVP scenarios in `data/scenarios/` ([benchmark.md §5](benchmark.md)); `scripts/validate_scenarios.py`; `scripts/seed_db.py`.
- APIs: list/filter/paginate, get (viewer vs owner schema), create, patch (versioning rule), clone, archive, validate, import, export, `GET /taxonomy`.
- UI: login page, scenario list with filters/badges, detail (visible input; ground truth tab owner-only), JSON editor with validate-before-save, import/export.

Acceptance
- [x] All 10 scenarios validate; 19 invalid-fixture cases fail with precise messages (`tests/test_scenario_schema.py`)
- [x] Seed is idempotent (second run reports `unchanged`; checked in CI)
- [x] Viewer API responses never include `ground_truth` or other hidden fields (test asserts on the raw payload)
- [x] Editing a locked version creates `version+1`; only the latest version is editable (test)
- [x] Scenarios listed, filtered, searched, inspected, cloned, archived, edited and validated in the UI (checked in the browser as viewer and owner)

Results: backend 74 tests (55 unit + 19 database), frontend 12 tests; ruff, oxlint, typecheck and build clean.

Implementation notes
- Added beyond the plan: `data/sops/catalog.json` (SOP slugs + section IDs, so scenarios can cite real
  `sop:` evidence now; section text is Phase 2), a scenario `as_of` field (simulated "now"),
  `POST /scenarios/{id}/restore`, recipient-name masking for viewers, login rate limiting.
- Passwords use Argon2id; tokens are HS256 JWTs (`JWT_SECRET`, refused in production if missing or weak).
- Generating frontend types with openapi-typescript is deferred; types are hand-written in `features/scenarios/types.ts`.
- Local development DB: Postgres 16.2 portable binaries (no Docker); tests use `TEST_DATABASE_URL`.

---

## Phase 2 — Mock logistics tools, policy, SOP search

**Goal:** a tool gateway that returns scenario data with evidence IDs and rejects invalid/forbidden calls.

Tasks
- `ScenarioDataView` (read-only, no ground truth) built from `mock_data`.
- Tool registry with the 10 tools (architecture.md §5), Pydantic args, typed `ToolResult`/`ToolError`.
- `ToolGateway` pipeline: permitted → budget → args → policy → injected latency/error → handler.
- `domain/policy.py` `policy-v1`.
- Synthetic SOP corpus in `data/sops/*.md` (delay comms, failed delivery, escalation/SLA, refund/reroute, response templates) with section IDs; `documents` + `document_chunks` tables; Postgres full-text `search_sop` limited to the scenario's permitted docs.
- Scenario-level fault injection: `{"tool": "get_carrier_status", "error": "timeout", "latency_ms": 3000}`.

Acceptance
- [x] Each read tool returns seeded data + correct evidence IDs; a golden test reads every scenario through the tools and confirms all required record evidence is reachable
- [x] Invalid args → `invalid_arguments` (with field names); non-permitted → `tool_not_permitted`; unknown → `unknown_tool`; gated → `policy_denied` (blocked, recorded, nothing executed); budget → `tool_budget_exceeded` (every attempt counts)
- [x] SOP search returns only permitted documents, ranked, with section IDs; 7 natural-language queries rank the right section first, and every required `sop:` evidence ID is found by its section title
- [x] Fault injection reproducible (two independent runs of the carrier-timeout scenario behave identically; per-call faults supported)

Results: backend 128 tests (99 unit + 29 database); ruff clean; seeding SOPs + scenarios is idempotent.

Implementation notes
- Code: `app/services/tools/` (`schemas`, `data_view`, `handlers`, `registry`, `gateway`), `app/domain/policy.py`,
  `app/domain/sop_corpus.py`, `app/services/sops/service.py`; migration 0003 adds `documents` and `document_chunks`
  (generated `tsvector` column, title weighted above body, GIN index).
- Search ORs the query words (`to_tsquery('english', 'a | b')`) and ranks with `ts_rank_cd`, because agent queries
  are long and AND-matching would often return nothing.
- policy-v1 also rejects `critical` escalations whose reason is not a safety or legal concern.
- Every call (including rejected ones) is a `ToolCallRecord` passed to an observer; Phase 4 plugs the trace collector in there.
- Simulated latency uses an injectable `sleep`, so tests don't wait; real runs do.
- No UI in this phase: tools are exercised by the agent from Phase 3 onwards.

---

## Phase 3 — Agent graph + rule-based agents + agent configs

**Goal:** LangGraph agent that completes a scenario through the tool gateway using a deterministic decider.

Tasks
- `agent_graph/`: state, nodes (`intake`, `decide`, `act`, `observe`, `finalize`), budgets, `submit_outcome` tool.
- `Decider` protocol; `RuleBasedDecider` profiles:
  - `rule-based-v1`: fetch shipment → events → carrier status (if carrier_id) → SOP search by category keywords → infer root cause from evidence heuristics → escalate per SLA heuristic → templated grounded response.
  - `rule-based-v2-flawed`: deliberately skips SOP search, ignores carrier errors, and states an ETA when one appears in any event — produces realistic, deterministic failures.
- `ModelProvider` protocol + `FakeProvider` (scripted turns) for graph unit tests.
- `build_agent_input()` (single choke point) + leakage test.
- `agent_configs` model, migration, CRUD/versioning API, seed the two rule-based configs; agents UI (list/detail/editor, API-key status).

Acceptance
- [x] `rule-based-v1` completes all 10 scenarios with a valid `AgentOutcome` via `scripts/run_agent.py`; it also matches the expected root cause and escalation decision in 10/10 and cites every required evidence ID (golden test)
- [x] Budgets stop runaway loops: a looping FakeProvider is stopped at `max_steps`; the gateway returns `tool_budget_exceeded` past `max_tool_calls`; a wall-clock deadline ends the run as `timeout`
- [x] Leakage test passes for all scenarios (agent input has exactly 5 fields; no scenario ID, title, description, tags, ground truth, rubric or author note)
- [x] Agent configs visible, created, validated, versioned, cloned and archived in the UI (checked in the browser)

Note: rule-based heuristics read **only** visible input and tool results — never ground truth.

Results: backend 156 tests (120 unit + 36 database), frontend 14 tests; lint, typecheck and build clean.

Implementation notes
- Graph nodes are `intake → decide → act → finalize` (tool results are appended in `act`; no separate `observe` node).
  Stop reasons: `completed`, `step_limit`, `timeout`, `malformed_output` (still invalid after one repair turn), `agent_error`.
- The agent input is narrower than the demo-viewer view: customer message, visible context, `now`, the full
  root-cause label list and permitted tool specs only. The scenario ID/title/category would hint at the answer.
- `rule-based-v2-flawed` fails as designed: wrong cause on the future-dated scan, ambiguity and carrier timeout;
  no escalation on carrier silence or refund demands; quotes the promised date as an ETA; attempts
  `request_refund` / `request_reroute` (blocked by policy, recorded) and promises a refund in its reply.
- Agent configs live in `data/agents/*.json`, are seeded by `seed_db.py`, and resolve `system_prompt` from
  `app/prompts/<prompt_version>.md` when not given. LLM providers (`gemini`, `openai`) can be configured but are
  not runnable until Phase 6; the providers endpoint reports only "configured / not configured".

---

## Phase 4 — Execution and trace

**Goal:** launch a run from the UI and inspect its complete observable trace.

Tasks
- Models + migration: `runs`, `trace_events`, `usage_counters`.
- `RunService` (create, caps, snapshots), `InProcessExecutor` (thread pool, cancel tokens, wall-clock timeout), startup sweeper.
- `TraceCollector` writes each event immediately; display-time redaction.
- API: `POST /runs` (202), `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/trace`, `POST /runs/{id}/cancel`; rate limit + caps.
- UI: run launcher (config + scenario), run detail with status polling, trace timeline, tool-call cards, JSON expander.

Acceptance
- [x] Launch → queued → running → completed visible in UI (checked in the browser: live status and a trace growing 7 → 9 → 17 events); trace complete and persisted after a real backend restart
- [x] Timeout and cancel produce clear states (tests for queued cancel, running cancel, running timeout, watchdog overrun; cancel also checked in the browser: stopped within ~1 s, mid tool latency)
- [x] Orphaned runs swept on startup (test; and in the browser: backend killed mid-run → run shown as `errored / infra / orphaned` with its partial trace kept)
- [x] Concurrency limit respected (unit test: 5 submissions, limit 2, peak 2; browser: 3 launches → running, running, queued)

Results: backend 180 tests (126 unit + 54 database), frontend 17 tests; lint, typecheck and build clean.
First performance review recorded in performance_review.md §7.

Implementation notes
- Code: `app/services/execution/` (`executor`, `worker`, `collector`, `service`), `app/api/v1/runs.py`,
  migration 0005 (`runs`, `trace_events`, `usage_counters`); frontend `features/runs/`.
- Status (`queued/running/completed/timed_out/cancelled/errored`) is separate from the agent's `stop_reason`
  and from `error_kind` (`agent` vs `infra`); `verdict`/`score` stay empty until Phase 5.
- Status changes are compare-and-set, so a watchdog timeout or a cancel is never overwritten by a late result.
- Cancellation and timeouts are cooperative (checked before every step and tool call; simulated tool latency
  waits on the cancel token) plus a watchdog at `timeout_s + RUN_WATCHDOG_GRACE_S` for stuck calls.
- SOP search opens a short session per query, so a run never holds a database transaction open.
- Launching a run locks the scenario version and agent config version it used.
- Also added: a 1 MB request body limit (413, NFR-03), a run-queue cap (`MAX_QUEUED_RUNS` → 429),
  per-principal run rate limit, the daily usage counter (`try_consume`, enforced for LLM runs in Phase 6),
  `scripts/perf_probe.py`, and Run buttons on scenario and agent pages.

---

## Phase 5 — Deterministic evaluator

**Goal:** every completed run gets an auditable score breakdown and verdict.

Tasks
- `domain/scoring.py`, `domain/constraints.py`, `services/evaluation` `eval-v1` per [benchmark.md §6–8](benchmark.md).
- `evaluation_results` model/migration; evaluation triggered at run end; `GET /runs/{id}/evaluation`.
- Golden tests: hand-built traces per scenario covering pass, wrong root cause, missing evidence, fabricated citation, forbidden attempt, missed escalation, unsupported ETA, compensation promise, timeout.
- UI: score summary, component bars, verdict + policy badge, assertion list linked to trace events.

Acceptance
- [x] Golden traces produce exactly the expected assertions, score and verdict (`tests/test_scoring.py`: pass, wrong root cause, missing evidence, fabricated citation, forbidden attempt, missed escalation, unsupported ETA, compensation promise, timeout, platform error, unnecessary escalation, invalid/disallowed calls, ordering, re-normalisation, missing required action, ignored tool failure)
- [x] A forbidden-action attempt yields `FAILED_POLICY` even with score ≥ threshold (golden test: score 80 ≥ 70, verdict FAILED_POLICY)
- [x] `rule-based-v1` vs `rule-based-v2-flawed` give different, explainable results on the 10 scenarios: v1 PASS 10/10 (all 100); v2 PASS 2, FAIL 2, FAILED_POLICY 6, each failure matching a designed flaw (`tests/test_evaluation.py`)

Results: backend 231 tests (170 unit + 61 database), frontend 19 tests; lint, typecheck and build clean.
Checked in the browser as viewer (verdict, gates, component bars, checks linked to trace steps, no expected
values) and as owner (expected vs actual shown).

Implementation notes
- Code: `app/domain/constraints.py` (response checks), `app/domain/scoring.py` (eval-v1, pure),
  `app/services/evaluation/service.py`, migration 0006 (`evaluation_results`); frontend `EvaluationPanel`.
- Scoring reads the saved trace, so every assertion cites `te:N` refs and runs can be re-scored
  (`POST /runs/{id}/evaluate`, `scripts/evaluate_runs.py`). Runs are scored automatically when they finish,
  including watchdog timeouts; orphaned runs get `ERROR`; cancelled runs are not scored.
- Demo viewers get verdict, score, components and pass/fail summaries; `expected`, `actual` and `detail` are
  owner-only because they reveal the ground truth.
- `scripts/run_agent.py` now prints verdict and score (scored in memory).
- Fixed during testing: a numeric-date pattern also matched the tail of ISO dates, flagging a supported ETA.

---

## Phase 6 — Gemini LLM agent

**Goal:** the same graph driven by Gemini Flash, safely within free-tier limits.

Tasks
- `GeminiProvider` (official SDK or langchain-google-genai): tool calling, `submit_outcome`, usage metadata,
  thinking minimised and **thought parts dropped**, timeout, retry/backoff for transient errors, RPM throttle, quota error mapping.
- `LLMDecider`; versioned prompt `prompts/agent_system_v1.md` (untrusted-data instruction, label list, citation requirement).
- Daily LLM cap; owner-only LLM runs; settings status endpoint shows "Gemini configured / not configured".
- Smoke test marked `llm` (skipped without key).
- Optional `OpenAIProvider` stub behind the same protocol (Later).

Acceptance
- [x] With a key: one scenario completes end-to-end with Gemini and is evaluated (smoke test: `delay_hub_congestion_001`
  PASS 100; in the browser: `policy_refund_demand_001` completed in 12.6 s and was scored, checks linked to the trace)
- [x] Without a key: app works; the LLM config shows "not configured"; launching one returns 409 `provider_not_configured`
- [x] No thought content in any persisted trace (DB test: a fake response with thought text and a thought signature;
  neither appears in trace events or run rows)
- [x] 429 from provider → `errored(provider_quota)`, verdict `ERROR`, readable UI message (test + UI test)

Results: backend 265 tests (+1 opt-in `llm` smoke test), frontend 21 tests; lint, typecheck and build clean.
Rule-based results unchanged (v1 PASS 10/10).

Implementation notes
- Code: `app/services/providers/` (`factory`, `gemini`, `throttle`, `errors`), seeded config
  `data/agents/gemini-flash-v1.v1.json` (`model_id: "default"` = the server's `GEMINI_MODEL`).
- SDK: official `google-genai`, imported only when a Gemini run starts. Default model `gemini-3.5-flash`
  (checked against the key on 2026-11-12: 2.5 Flash is closed to new keys; 3.8 Flash was overloaded and
  rejects minimal thinking). Google may serve a newer model under that ID (traces showed `gemini-3.6-flash`);
  `versions.model` records what was requested, each agent turn records what answered.
- Thinking: `thinking_level=minimal` (`thinking_budget=0` for 2.5 models), `include_thoughts=False`, and thought
  parts are dropped while parsing anyway. Gemini 3 **thought signatures** (opaque tokens it needs back on the next
  turn) are kept in the provider's memory for one run and never stored.
- Tool calling uses mode `ANY` (every turn is a tool call; the run ends with `submit_outcome`); tool JSON schemas
  have `$ref`s inlined and go in as `parameters_json_schema`.
- Provider failures raise typed `ProviderError`s; the graph stops with `provider_error` and the run ends
  `errored` / `infra` / verdict `ERROR` with `error.code` = `provider_quota`, `provider_unavailable`,
  `provider_auth` or `provider_bad_request`. A cancel or timeout during a provider wait is still reported as such.
- Retries: `max_retries` from the config, backoff 1 s → 4 s, the server's `retryDelay` honoured up to 20 s, never
  past the run deadline. Per-request timeout 20 s, never below Gemini's 10 s minimum (found in the browser test:
  Gemini returns 400 for shorter deadlines).
- Limits: process-wide throttle `GEMINI_RPM_LIMIT` (default 5/min); the daily cap is taken last at launch
  (429 `llm_daily_cap_reached`, no run created; rule-based runs never count). `/agents/providers` shows the model,
  the cap and (owner only) runs left today.
- UI: launcher says why an agent can't run (owner only / not configured / daily limit reached) and shows the
  remaining quota; run detail explains provider errors in plain language and shows model and token usage.
- Observed in the first browser run: Gemini answered a refund demand correctly (right cause, escalated, no
  compensation promise), but eval-v1 flagged `must_not_invent_eta` because the reply mentioned the *past*
  promised date, and missed a paraphrased delay explanation. These are evaluator false positives to address in
  an evaluator version bump, not Phase 6 changes.

---

## Phase 7 — Failure diagnosis (+ optional judge)

Tasks
- `domain/diagnosis_rules.py` `diag-v1` (architecture.md §8); `failure_reports` model; `GET /runs/{id}/failure-report`.
- `insufficient_evidence` fallback.
- Optional LLM judge for tone/clarity/grounding (`prompts/judge_v1.md`), structured JSON output, stored separately; off by default; disabled for viewers.
- UI: failure report panel with severity, stage, cited trace events (click → scroll to event).

Acceptance
- [ ] Every failure item cites an assertion and ≥1 trace ref, or is `insufficient_evidence`
- [ ] Unit tests for every rule in the mapping table
- [ ] Judge off ⇒ weights re-normalised; judge on ⇒ judge result stored with model + prompt version

---

## Phase 8 — Benchmark suites and regression

Tasks
- `benchmark_suites`, `suite_memberships`, `suite_runs`; suite CRUD (explicit list or tag); suite run with concurrency limit and Gemini throttle.
- Suite summary metrics ([benchmark.md §9](benchmark.md)); `domain/comparison.py`; comparison API.
- Optional repeats N per scenario with flaky detection.
- UI: suite list, suite run progress, comparison page (fixed / newly failed / safety regressions / deltas).

Acceptance
- [ ] Run the MVP suite with both rule-based configs and compare: classification matches golden expectation
- [ ] Version mismatches flagged "not comparable"
- [ ] Comparison is computed from persisted data only

---

## Phase 9 — Dashboard and reports

Tasks
- `GET /dashboard/summary`; KPI cards, failure distribution, version comparison chart, recent runs.
- `is_demo` labelling everywhere; "unknown" for unmeasured values.
- Report service: run + benchmark reports; JSON and CSV export.
- UX polish: loading/empty/error/success states, backend-waking banner.

Acceptance
- [ ] Every KPI traceable to a SQL query over persisted runs (tests on seeded fixtures)
- [ ] Exports include run IDs, scenario versions, agent version, evaluator version, breakdown, failures

---

## Phase 10 — RAG and expanded scenarios

Tasks
- Expand SOP corpus; chunking; Gemini embeddings into pgvector (`document_chunks.embedding`) with lexical fallback.
- Citation quality assertions (cited ⊆ retrieved; required SOP sections cited).
- Expand to **30+ scenarios** across all 10 categories, including prompt-injection and ambiguity cases ([benchmark.md §5.2](benchmark.md)).

Acceptance
- [ ] Agent retrieves permitted SOP evidence; evaluator checks citation quality
- [ ] 30+ scenarios validate; golden tests for injection scenarios pass with rule-based-v1

---

## Phase 11 — Deployment

Follow [deployment.md](deployment.md): Neon DB → Render backend → Vercel frontend → secrets/CORS → migrations + seed → smoke test → checklist.

Acceptance
- [ ] Public URL works end-to-end (viewer can run rule-based benchmark; owner can run Gemini within cap)
- [ ] Deployment checklist (deployment.md §9) fully ticked; no secrets in Git or bundle

---

## Phase 12 — Portfolio polish

- Demo video (2–3 min): scenario → run → trace → failure → regression comparison.
- Finalise `context/` docs, benchmark methodology and limitations in README.
- Record real measured results in [benchmark.md §15](benchmark.md) and [performance_review.md](performance_review.md).
- Resume bullets only for implemented and measured features.

---

## Cross-phase rules

- Tests accompany every evaluator/policy/scoring change.
- Migrations are additive; never edit an applied migration.
- Update `context/` docs in the same change that alters behaviour.
- No phase may introduce a paid dependency or a CI step that calls an LLM.
