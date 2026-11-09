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
| 4 | Execution and trace | ⬜ | 4 |
| 5 | Deterministic evaluator | ⬜ | 5 |
| 6 | Gemini LLM agent | ⬜ | 3 (second half) |
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
- [ ] Launch → queued → running → completed visible in UI; trace complete and persisted after restart
- [ ] Timeout and cancel produce clear states (tests)
- [ ] Orphaned runs swept on startup (test)
- [ ] Concurrency limit respected (test with 5 submissions, limit 2)

---

## Phase 5 — Deterministic evaluator

**Goal:** every completed run gets an auditable score breakdown and verdict.

Tasks
- `domain/scoring.py`, `domain/constraints.py`, `services/evaluation` `eval-v1` per [benchmark.md §6–8](benchmark.md).
- `evaluation_results` model/migration; evaluation triggered at run end; `GET /runs/{id}/evaluation`.
- Golden tests: hand-built traces per scenario covering pass, wrong root cause, missing evidence, fabricated citation, forbidden attempt, missed escalation, unsupported ETA, compensation promise, timeout.
- UI: score summary, component bars, verdict + policy badge, assertion list linked to trace events.

Acceptance
- [ ] Golden traces produce exactly the expected assertions, score and verdict
- [ ] A forbidden-action attempt yields `FAILED_POLICY` even with score ≥ threshold
- [ ] `rule-based-v1` vs `rule-based-v2-flawed` give different, explainable results on the 10 scenarios

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
- [ ] With a key: one scenario completes end-to-end with Gemini and is evaluated
- [ ] Without a key: app works; LLM configs show "not configured"; launching one returns a clear 409/422
- [ ] No thought content in any persisted trace (test with a fake response containing thought parts)
- [ ] 429 from provider → `errored(provider_quota)` with readable UI message

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
