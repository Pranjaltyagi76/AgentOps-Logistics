# Architecture — AgentOps Logistics

> Concrete structure: modules, interfaces, data model, API, trace schema and frontend layout.
> The *why* behind these choices is in [system_design.md](system_design.md) (decisions D-01…D-16).
> Scoring semantics are in [benchmark.md](benchmark.md).
>
> Last updated: 2026-11-07 (planning). Update this file whenever implementation diverges.

---

## 1. Component overview

```text
frontend (React SPA)
  pages → features/* → hooks (TanStack Query) → lib/api (axios, generated OpenAPI types)
        │ REST /api/v1 (JWT bearer)
        ▼
backend (FastAPI, modular monolith)
  api/v1 routers ──▶ services ──▶ domain (pure logic) ──▶ db (SQLAlchemy repositories)
                       │
                       ├─ execution: RunService → RunExecutor ─▶ agent graph (LangGraph)
                       │                                          ├─ Decider: RuleBasedDecider | LLMDecider(ModelProvider)
                       │                                          └─ ToolGateway → PolicyEngine → MockTools(ScenarioDataView)
                       │                                 TraceCollector (persists every event)
                       ├─ evaluation: Evaluator (assertions → score → verdict)
                       ├─ diagnosis: Diagnoser (rules → failure reports)
                       ├─ benchmarks: SuiteService, ComparisonService
                       └─ reports: ReportService (JSON/CSV)
        │
        ▼
PostgreSQL (Neon / local Docker)
```

**Layering rules**
- Routers: parse/validate, authz, call one service method, map to response schema. No business logic, no DB queries, no model calls.
- Services: orchestration + transactions. Receive a `Session` and providers via dependency injection.
- Domain (`app/domain/…`): pure functions/classes (scoring, policy, diagnosis rules, comparison). No I/O → trivially unit-testable.
- DB: SQLAlchemy models + small repository functions. API schemas (`app/schemas`) are separate from ORM models.

## 2. Backend directory structure

```text
backend/
├── app/
│   ├── main.py                  # app factory, middleware, routers, startup sweeper
│   ├── core/
│   │   ├── config.py            # Settings (pydantic-settings), SecretStr for secrets
│   │   ├── security.py          # password hashing, JWT encode/decode, role deps
│   │   ├── logging.py           # JSON logs, request_id/run_id contextvars, secret redaction
│   │   ├── errors.py            # AppError hierarchy + exception handlers (error envelope)
│   │   └── limits.py            # rate limit + body size middleware, usage caps
│   ├── api/v1/
│   │   ├── health.py  auth.py  scenarios.py  agents.py  runs.py
│   │   ├── suites.py  comparisons.py  reports.py  dashboard.py  settings.py
│   ├── schemas/                 # Pydantic API + domain schemas
│   │   ├── scenario.py          # ScenarioSpec (file/import schema), ScenarioOut, ScenarioOwnerOut
│   │   ├── agent.py  run.py  trace.py  evaluation.py  diagnosis.py  suite.py  common.py
│   ├── domain/
│   │   ├── taxonomy.py          # categories, root-cause enums, failure types, evidence-ID parsing
│   │   ├── policy.py            # PolicyEngine (pure)
│   │   ├── scoring.py           # assertion → component scores → weighted score → verdict
│   │   ├── constraints.py       # response-constraint checkers (regex/keyword)
│   │   ├── diagnosis_rules.py   # assertion → failure type/stage/severity map
│   │   └── comparison.py        # baseline vs candidate classification
│   ├── db/
│   │   ├── base.py  session.py  # engine, SessionLocal, get_db dependency
│   │   ├── models/              # one module per aggregate
│   │   └── migrations/          # Alembic
│   ├── services/
│   │   ├── scenarios/           # CRUD, versioning, import/export, seeding
│   │   ├── agents/              # config CRUD/versioning
│   │   ├── execution/           # RunService, RunExecutor, sweeper, build_agent_input
│   │   ├── agent_graph/         # LangGraph graph, state, deciders, prompts/
│   │   ├── providers/           # ModelProvider protocol, GeminiProvider, FakeProvider, (OpenAIProvider)
│   │   ├── tools/               # registry, gateway, mock tool implementations, sop_search
│   │   ├── tracing/             # TraceCollector, redaction
│   │   ├── evaluation/          # Evaluator (uses domain/scoring), optional judge
│   │   ├── diagnosis/           # Diagnoser
│   │   ├── benchmarks/          # SuiteService, ComparisonService
│   │   └── reports/             # ReportService, CSV/JSON writers
│   └── prompts/                 # versioned prompt files: agent_system_v1.md, judge_v1.md
├── tests/  (unit/ integration/ golden/ — see §12)
├── pyproject.toml
└── .env.example
```

Create folders only when the phase that needs them starts (PROJECT.md §21).

## 3. Key interfaces

```python
# services/providers/base.py
class ModelTurn(BaseModel):
    text: str | None                 # visible assistant text only (thought parts stripped)
    tool_calls: list[ToolCallRequest]
    usage: Usage | None              # input/output tokens if provider reported them
    raw_model_id: str

class ModelProvider(Protocol):
    name: str                        # "gemini" | "openai" | "fake"
    def generate(self, messages: list[Message], tools: list[ToolSpec],
                 *, temperature: float, timeout_s: float) -> ModelTurn: ...

# services/agent_graph/deciders.py
class Decider(Protocol):
    """Chooses the next action for the graph's `decide` node."""
    def decide(self, state: LogisticsAgentState) -> Decision: ...   # tool calls or final outcome

class RuleBasedDecider:   ...  # deterministic heuristics over visible state; profile = "v1" | "v2_flawed"
class LLMDecider:         ...  # wraps a ModelProvider

# services/tools/registry.py
class ToolDef(BaseModel):
    name: str
    description: str
    args_model: type[BaseModel]
    kind: Literal["read", "mock_write"]
    policy_gated: bool               # True for request_refund / request_reroute
    handler: Callable[[ScenarioDataView, BaseModel], ToolResult]

# services/tools/gateway.py
class ToolGateway:
    def call(self, name: str, raw_args: dict) -> ToolResult:
        # 1 tool permitted for this scenario+config?  else ToolError("tool_not_permitted")
        # 2 budget left?                                 else ToolError("tool_budget_exceeded")
        # 3 args valid (Pydantic)?                       else ToolError("invalid_arguments")
        # 4 PolicyEngine.check(name, args, ctx)?         else ToolError("policy_denied")
        # 5 simulated latency/error injection (scenario-defined)
        # 6 handler(...) → ToolResult (with evidence_ids)
        # every branch emits trace events via TraceCollector
        ...

# services/execution/executor.py
class RunExecutor(Protocol):
    def submit(self, run_id: UUID) -> None: ...
    def cancel(self, run_id: UUID) -> None: ...

class InProcessExecutor:   # ThreadPoolExecutor(max_workers=MAX_CONCURRENT_RUNS) + cancel tokens
    ...
# Later: DbQueueExecutor (separate worker, SELECT … FOR UPDATE SKIP LOCKED)

# services/evaluation/evaluator.py
class Evaluator:
    version: str = "eval-v1"
    def evaluate(self, scenario: ScenarioSpec, trace: list[TraceEvent],
                 outcome: AgentOutcome | None, run: RunFacts) -> EvaluationResult: ...

# services/diagnosis/diagnoser.py
class Diagnoser:
    version: str = "diag-v1"
    def diagnose(self, evaluation: EvaluationResult, trace: list[TraceEvent]) -> list[FailureReportItem]: ...
```

## 4. Agent graph (LangGraph)

```text
START → intake → decide ──(tool calls)──▶ act ──▶ observe ──▶ decide …
                   │                                            ▲
                   │(submit_outcome)                            │ step/tool budget check
                   ▼                                            │
               finalize ──▶ END              (budget exceeded → finalize with limit_exceeded)
```

| Node | Responsibility |
|---|---|
| `intake` | Load visible input into state; add system prompt + the global root-cause label list |
| `decide` | Call the `Decider` (rule-based or LLM) → either tool-call requests or `submit_outcome` |
| `act` | Execute each requested tool via `ToolGateway` |
| `observe` | Append tool results to `messages`; add returned evidence IDs to `evidence` |
| `finalize` | Validate `AgentOutcome`; on invalid → one repair turn (LLM only) → else error |

State (extends PROJECT.md §7.2):

```python
class LogisticsAgentState(TypedDict):
    run_id: str
    scenario_id: str
    customer_message: str
    visible_context: dict
    messages: list            # visible conversation incl. tool results (no thought parts)
    evidence: list[dict]      # {evidence_id, source_tool, te_ref}
    proposed_root_cause: str | None
    proposed_actions: list[dict]
    escalation_required: bool
    final_response: str | None
    final_outcome: dict | None
    errors: list[dict]
    step_count: int
    tool_call_count: int
```

`submit_outcome` tool args = `AgentOutcome` (PROJECT.md §7.3) with `root_cause` constrained to the global root-cause enum (which includes `insufficient_evidence`).

## 5. Tools and policy

| Tool | Kind | Default permission | Evidence IDs returned |
|---|---|---|---|
| `get_shipment(shipment_id)` | read | allowed | `shipment:<id>` |
| `get_tracking_events(shipment_id)` | read | allowed | `event:<shipment_id>:<seq>` per event |
| `get_carrier_status(carrier_id)` | read | allowed | `carrier:<carrier_id>` |
| `get_ticket(ticket_id)` | read | allowed | `ticket:<id>` |
| `search_sop(query)` | read | allowed (scenario's permitted docs only) | `sop:<doc_slug>#<section>` |
| `create_support_ticket(payload)` | mock_write | allowed | `action:ticket:<n>` |
| `request_escalation(payload)` | mock_write | allowed | `action:escalation:<n>` |
| `send_customer_message(payload)` | mock_write (outbox) | allowed | `action:message:<n>` |
| `request_reroute(payload)` | mock_write | **policy-gated, denied by default** | — |
| `request_refund(payload)` | mock_write | **policy-gated, denied by default** | — |

`PolicyEngine` rules (pure, versioned `policy-v1`):
- Gated tools are denied unless the scenario's `policy.authorizations` explicitly authorizes them (none do in MVP).
- `request_escalation` requires a non-empty `reason` and a `severity` in an enum.
- `send_customer_message` text is checked by the response-constraint checkers *at evaluation time* (not blocked at call time — we score what the agent tried to say).
- Every denial returns `ToolError(code="policy_denied", rule_id=…)` to the agent and emits a `policy_denied` trace event.

Mock writes are stored only in the run's trace/outbox; nothing is sent anywhere.

## 6. Trace event schema

```python
class TraceEvent(BaseModel):
    id: UUID
    run_id: UUID
    seq: int                     # 1..n, referenced as "te:<seq>"
    event_type: Literal[
        "run_started", "node_enter", "node_exit",
        "model_request", "model_response",        # metadata + visible text; never thought parts
        "tool_call", "tool_result", "tool_error", "policy_denied",
        "outcome_submitted", "limit_exceeded", "run_error", "run_finished"]
    node_name: str | None
    tool_name: str | None
    input_json: dict | None      # tool args / model request summary (no secrets)
    output_json: dict | None     # tool result / visible model text / outcome
    error_json: dict | None      # {code, message, retryable}
    evidence_ids: list[str]      # evidence returned by this event (tool_result)
    duration_ms: int | None
    usage_json: dict | None      # tokens on model_response when reported
    timestamp: datetime          # UTC
```

Redaction is applied at **read/export** time (display serializers), so stored traces remain usable by the evaluator; stored data is synthetic.

## 7. Evaluation pipeline

```text
trace + outcome + scenario ground truth
   │
   ├─ extract facts: tools called (ordered), arg validity, policy denials, evidence returned,
   │                 evidence cited, escalation calls, messages sent, final response text
   ├─ run assertions (each → {id, component, passed, expected, actual, cites:[te refs], gate:bool})
   ├─ component scores ∈ [0,1]  (formulas: benchmark.md §6)
   ├─ weighted score 0–100 with re-normalisation for disabled components
   ├─ gates → verdict (FAILED_POLICY overrides; then PASS/FAIL by threshold + root cause)
   └─ persist EvaluationResult(evaluator_version, score_breakdown, assertions, verdict, policy_violations)
```

## 8. Diagnosis rules (diag-v1)

| Failed assertion | Failure type | Likely stage | Default severity |
|---|---|---|---|
| `root_cause_match` | `wrong_root_cause` | decision | high |
| `required_evidence_cited` | `missing_evidence` | retrieval | medium |
| `citation_was_retrieved` | `unsupported_claim` | response | high |
| `required_tool_called` | `required_action_missing` (action tool) / `missing_evidence` (read tool) | planning | medium |
| `no_disallowed_tool` | `wrong_tool` | planning | medium |
| `tool_args_valid` | `invalid_tool_arguments` | tool_use | medium |
| `tool_error_handled` | `tool_failure_unhandled` | tool_use | high |
| `no_forbidden_action` (gate) | `forbidden_action` | policy | critical |
| `escalation_expected` | `missed_escalation` (gate) / `unnecessary_escalation` | decision | critical / low |
| `constraint:*` (ETA, compensation — gates) | `unsupported_claim` | response | critical |
| `constraint:*` (others) | `response_not_grounded` | response | medium |
| `within_time_limit` | `timeout` | execution | high |
| `outcome_valid` / run error | `agent_crash` | execution | high |
| no failed assertion explains a FAIL | `insufficient_evidence` | unknown | low |

Every report item cites the assertion ID and the trace refs it cites. Confidence: `high` if the assertion is exact-match with direct trace evidence, `medium` if heuristic (regex/keyword), `low` otherwise.

## 9. Data model

Refines PROJECT.md §14. All PKs are UUID v4; all timestamps `timestamptz` UTC; JSON columns are `JSONB`.

| Table | Key columns (beyond `id`, `created_at`) | Constraints / indexes |
|---|---|---|
| `users` | `email`, `hashed_password`, `role` (`owner`) | unique(`email`) |
| `workspaces` | `name`, `owner_user_id` | — |
| `scenarios` | `workspace_id?`, `scenario_key`, `version`, `title`, `category`, `difficulty`, `status` (`draft`/`active`/`archived`), `tags` (text[]), `scenario_json`, `is_locked` (used in a run), `updated_at` | unique(`scenario_key`,`version`); idx(`category`), idx(`status`), GIN(`tags`) |
| `agent_configs` | `workspace_id?`, `name`, `version`, `provider`, `model_id`, `prompt_version`, `prompt`, `config_json` (temperature, tools, limits), `is_locked` | unique(`name`,`version`) |
| `benchmark_suites` | `name`, `description`, `tag_filter?` | — |
| `suite_memberships` | `suite_id`, `scenario_key`, `pinned_version?` | unique(`suite_id`,`scenario_key`) |
| `suite_runs` | `suite_id`, `agent_config_id`, `status`, `started_at`, `finished_at`, `summary_json`, `is_demo` | idx(`suite_id`,`created_at`) |
| `runs` | `scenario_id` (version row), `agent_config_id`, `suite_run_id?`, `status`, `verdict?`, `error_kind?` (`agent`/`infra`), `started_at`, `finished_at`, `latency_ms`, `usage_json?`, `final_outcome_json?`, `score?`, `policy_failed`, `error_json?`, `config_snapshot_json`, `is_demo`, `triggered_by_role` | idx(`status`,`created_at`), idx(`suite_run_id`), idx(`agent_config_id`) |
| `trace_events` | columns of §6 | unique(`run_id`,`seq`); idx(`run_id`) |
| `evaluation_results` | `run_id`, `evaluator_version`, `score_breakdown_json`, `assertions_json`, `task_success`, `verdict`, `policy_violations_json`, `judge_json?` | unique(`run_id`,`evaluator_version`) |
| `failure_reports` | `run_id`, `diagnoser_version`, `failure_type`, `severity`, `likely_stage`, `evidence_json`, `diagnosis`, `debugging_recommendation`, `confidence` | idx(`run_id`), idx(`failure_type`) |
| `documents` | `slug`, `version`, `title`, `document_type`, `content`, `metadata_json` | unique(`slug`,`version`) |
| `document_chunks` | `document_id`, `section_id`, `text`, `tsv` (tsvector), `embedding?` (vector, Phase 10) | unique(`document_id`,`section_id`); GIN(`tsv`) |
| `usage_counters` | `day` (date UTC), `key` (e.g. `llm_runs`), `count` | unique(`day`,`key`) |

Seeded rows set `is_demo = true`.

## 10. API

Prefix `/api/v1`. Endpoint list in PROJECT.md §15, plus:

| Added endpoint | Purpose |
|---|---|
| `POST /auth/login`, `POST /auth/demo`, `GET /auth/me` | auth (FR-11) |
| `GET /dashboard/summary` | KPIs computed server-side |
| `GET /settings/status` | provider configured?, limits, versions (no secrets) |
| `GET /taxonomy` | categories, root-cause enums, failure types, tool names (for UI and editor validation) |
| `POST /scenarios/validate` | validate JSON without saving |
| `POST /scenarios/{id}/archive`, `POST /scenarios/{id}/restore` | archive / restore every version (instead of DELETE) |
| `GET /scenarios/export`, `GET /scenarios/{id}/export` | owner-only JSON export in schema key order |

**Conventions**
- Pagination: `?limit=` (≤100, default 20) `&cursor=` → `{items, next_cursor}`.
- Error envelope: `{"error": {"code": "scenario_not_found", "message": "...", "details": {...}, "request_id": "..."}}` with correct HTTP status (400 validation, 401, 403, 404, 409 version conflict / locked, 422 schema, 429 rate/cap, 503 db/provider).
- `POST /runs` returns **202** with `{run_id, status}`; clients poll `GET /runs/{id}`.
- Viewer responses use `*Out` schemas without `ground_truth`; owner gets `*OwnerOut`.

## 11. Frontend architecture

```text
frontend/src/
├── main.tsx  app/ (router.tsx, providers.tsx, layout/AppShell.tsx)
├── lib/      api.ts (axios instance, auth header, error normalisation), auth.ts, format.ts
├── types/    (planned) api.d.ts generated by openapi-typescript; until then feature-local types.ts files
├── components/ ui/ (shadcn), StatusBadge, VerdictBadge, DemoDataBadge, JsonExpander, EmptyState, ErrorState
└── features/
    ├── dashboard/   DashboardPage, KpiCards, FailureDistributionChart, VersionComparisonChart
    ├── scenarios/   ScenarioListPage, ScenarioDetailPage, ScenarioEditorPage (JSON editor + validate)
    ├── agents/      AgentListPage, AgentDetailPage, AgentEditor
    ├── runs/        RunLauncherPage, RunDetailPage, TraceTimeline, ToolCallCard, AssertionList, FailureReportPanel
    ├── benchmarks/  SuiteListPage, SuiteRunPage, ComparisonPage
    ├── reports/     ReportPage, ExportControls
    └── settings/    SettingsPage
```

Routes: `/` dashboard · `/scenarios` · `/scenarios/:id` · `/scenarios/:id/edit` · `/agents` · `/agents/:id` ·
`/runs/new` · `/runs/:id` · `/suites` · `/suite-runs/:id` · `/compare?baseline=&candidate=` · `/reports/:suiteRunId` · `/settings` · `/login`.

- Server state only through TanStack Query; run detail polls every 1.5 s while `status ∈ {queued, running}`.
- Role-aware UI hides owner-only actions, but the backend is the enforcement point.
- A global "backend waking up" banner when the first request exceeds 5 s.

## 12. Configuration

All settings via `app/core/config.py` (pydantic-settings, `.env` locally). Full variable table in [deployment.md §3](deployment.md).

## 13. Logging and observability

- JSON logs: `timestamp, level, logger, message, request_id, run_id, suite_run_id, event`.
- `request_id` from `X-Request-ID` header or generated; returned in responses and error envelopes.
- Log filter redacts `GEMINI_API_KEY`, JWTs and `password` fields.
- Optional later: LangSmith (dev only), OpenTelemetry.

## 14. Testing architecture

| Layer | Location | Notes |
|---|---|---|
| Unit | `tests/unit/` | domain modules (scoring, policy, constraints, diagnosis rules, comparison), schema validation |
| Integration | `tests/integration/` | FastAPI TestClient + real Postgres (Docker/CI service container); each test in a rolled-back transaction |
| Golden | `tests/golden/` | per scenario: recorded or scripted trace → expected assertions/verdict; rule-based agent end-to-end |
| Leakage | `tests/integration/test_leakage.py` | serialized agent input contains no ground-truth values for every scenario |
| Provider smoke | `tests/smoke/` | `@pytest.mark.llm`, skipped unless `GEMINI_API_KEY` set; never in CI |
| Frontend | `frontend/src/**/*.test.tsx` | Vitest + Testing Library; API mocked with MSW |
