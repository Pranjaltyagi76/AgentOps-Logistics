# AgentOps Logistics — Requirements

> **Source of truth:** [PROJECT.md](PROJECT.md). This file restates its requirements as a numbered,
> testable checklist and adds the decisions agreed on 2026-11-07 that resolve gaps in it.
> If this file and PROJECT.md disagree, raise it and fix whichever is wrong — do not silently pick one.
>
> **Status:** Planning complete. No requirement is implemented yet.

Priority legend: **MVP** = required for the first complete vertical slice · **Full** = required for the
portfolio-ready Definition of Done · **Later** = optional / nice-to-have.
"Phase" refers to [context/phasewise_roadmap.md](context/phasewise_roadmap.md).

---

## 1. Purpose

Build a web platform that tests AI agents operating in logistics customer-experience (CX) and shipment
troubleshooting workflows. It runs a candidate agent against reproducible, versioned scenarios with mocked
tools, records an observable trace, scores the run deterministically against hidden ground truth, diagnoses
failures with cited evidence, and compares agent versions for regressions.

It is **not** a shipment-management product, not production-ready, and not a claim that agent evaluation is novel.

## 2. Users and roles

| Role | Can | Cannot |
|---|---|---|
| **Owner** (evaluator / developer) — single account | Create/edit/clone/archive scenarios and agent configs, launch any run (including real Gemini runs, within the daily cap), view hidden ground truth, export reports | — |
| **Demo viewer** — passwordless "demo login" | View seeded and live runs, reports, dashboard; launch runs with the **rule-based (no-LLM) agents only**, rate-limited | Edit scenarios or agent configs, see hidden ground truth, launch LLM-backed runs, see secrets |

Single workspace for the MVP; every core table carries a nullable `workspace_id` so multi-workspace can be added later without rewriting entities.

---

## 3. Functional requirements

### FR-01 Scenario catalog
| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-01.1 | List scenarios with filters: category, difficulty, status, tags; free-text search on title; paginated | MVP | 1 |
| FR-01.2 | Scenario detail shows visible input (customer message, visible context, mock data, tools) | MVP | 1 |
| FR-01.3 | Ground truth and evaluation rules visible **only** to the owner role | MVP | 1 |
| FR-01.4 | Create and edit scenarios via a JSON editor with server-side schema validation and inline errors | MVP | 1 |
| FR-01.5 | Clone and archive scenarios | MVP | 1 |
| FR-01.6 | Editing a scenario version that has been used in any run creates a new version; used versions are immutable | MVP | 1 |
| FR-01.7 | Import/export scenarios as JSON (single and bulk) | MVP | 1 |
| FR-01.8 | Form-based scenario editor (in addition to JSON editor) | Later | — |

### FR-02 Scenario dataset
| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-02.1 | Each scenario contains every field listed in PROJECT.md §FR-02, validated by a Pydantic model | MVP | 1 |
| FR-02.2 | Root cause is a label from a **single closed global enum** (independent of scenario category) (see [context/benchmark.md §2](context/benchmark.md)) | MVP | 1 |
| FR-02.3 | Every mock record and SOP section has a **stable evidence ID**; ground-truth `required_evidence` references those IDs | MVP | 1 |
| FR-02.4 | `forbidden_actions` and `required_actions` reference **real tool names** from the tool registry; validation rejects unknown names | MVP | 1 |
| FR-02.5 | A scenario that lists a forbidden action must expose that tool in `available_tools` (so the attempt is observable) | MVP | 1 |
| FR-02.6 | 10 validated scenarios for MVP; 30+ for the full benchmark | MVP / Full | 1 / 10 |
| FR-02.7 | Scenario files live in `data/scenarios/*.json`; a `validate_scenarios` script and CI check validate them | MVP | 1 |

### FR-03 Agent configuration
| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-03.1 | Register config: name, version, provider (`rule_based` \| `gemini` \| `openai`), model ID, temperature, system prompt, tool set, max steps, max tool calls, timeout, retries | MVP | 3 |
| FR-03.2 | A config used in a run is immutable; editing creates a new version | MVP | 3 |
| FR-03.3 | Every run stores a full snapshot of the config and prompt it used | MVP | 4 |
| FR-03.4 | API keys live only in server environment; the UI shows only "configured / not configured" | MVP | 3 |
| FR-03.5 | No provider secret is ever stored in a DB row, log line, trace, or API response | MVP | all |
| FR-03.6 | OpenAI adapter | Later | 6 |

### FR-04 Agent execution
| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-04.1 | Run a selected agent config against a selected scenario version | MVP | 4 |
| FR-04.2 | Agent receives only `customer_message`, `visible_context`, and descriptions of permitted tools | MVP | 4 |
| FR-04.3 | An automated test asserts the exact agent input contains no ground-truth or evaluator content | MVP | 4 |
| FR-04.4 | Record each tool call and result, run start/end, status, error, latency, usage metadata when the provider returns it | MVP | 4 |
| FR-04.5 | Enforce max steps, max tool calls, max retries, wall-clock timeout; timeout produces a clear `timed_out` state | MVP | 3–4 |
| FR-04.6 | Cancellation of queued/running runs | Full | 4 |
| FR-04.7 | Configurable global concurrency limit (default 2) and a daily cap on LLM-backed runs (default 50) | MVP | 4 |
| FR-04.8 | On backend start, runs left in `queued`/`running` by a crash or sleep are marked `errored` with reason `orphaned` | MVP | 4 |

### FR-05 Trace viewer
| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-05.1 | Timeline of trace events: node transitions, agent messages, tool calls (name, args, result, duration, error/retry), final answer | MVP | 4 |
| FR-05.2 | Evaluator assertions shown alongside the trace, linked to the trace events they cite | MVP | 5 |
| FR-05.3 | Sensitive fields redacted in displayed tool results | MVP | 4 |
| FR-05.4 | **No chain-of-thought**: model "thought" parts are discarded before persistence; the UI shows only observable actions | MVP | 3, 6 |
| FR-05.5 | Readable cards by default, raw JSON behind an expander | MVP | 4 |

### FR-06 Evaluation engine
| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-06.1 | Deterministic checks: root cause, evidence, tool correctness, arguments, required actions, forbidden actions, escalation, structured response constraints | MVP | 5 |
| FR-06.2 | Hard safety gates override the score (verdict `FAILED_POLICY`) | MVP | 5 |
| FR-06.3 | Weighted 0–100 score; per-scenario weights; weights re-normalised when a component is disabled (e.g. no judge) | MVP | 5 |
| FR-06.4 | Evaluator is versioned; every result stores `evaluator_version` | MVP | 5 |
| FR-06.5 | Optional LLM judge for tone/clarity/grounding only; stores judge model, prompt version, rubric, output separately; never decides safety | Full | 7 |
| FR-06.6 | Golden tests: fixed traces → fixed evaluator outputs | MVP | 5 |

### FR-07 Failure diagnosis
| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-07.1 | Rule-based mapping from failed assertions to failure type, severity, likely stage, explanation, debugging direction | MVP | 7 |
| FR-07.2 | Every diagnosis cites trace event refs and/or assertion IDs; otherwise `insufficient_evidence` | MVP | 7 |
| FR-07.3 | Optional LLM-written narrative constrained to structured output and to the cited evidence | Later | 7 |

### FR-08 Regression testing
| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-08.1 | Benchmark suites (by explicit list or tag) | MVP | 8 |
| FR-08.2 | Run one config across a suite with the concurrency limit | MVP | 8 |
| FR-08.3 | Compare a candidate suite run to a baseline: newly failed, fixed, score deltas, safety regressions, latency and cost deltas | MVP | 8 |
| FR-08.4 | Comparison only pairs identical `scenario_key` + `version`; mismatches are flagged "not comparable" | MVP | 8 |
| FR-08.5 | Optional repeats per scenario (N) to expose non-determinism ("flaky" flag) | Full | 8 |

### FR-09 Dashboard
| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-09.1 | KPIs listed in PROJECT.md §FR-09, computed from persisted data only | MVP | 9 |
| FR-09.2 | Seeded/demo runs carry `is_demo = true` and are visibly labelled | MVP | 9 |
| FR-09.3 | Unknown values show "unknown"/"—", never a fabricated number | MVP | 9 |

### FR-10 Reports
| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-10.1 | Run report and benchmark report including run IDs, scenario versions, agent version, evaluator version, score breakdown, failures | MVP | 9 |
| FR-10.2 | Export JSON and CSV | MVP | 9 |
| FR-10.3 | PDF export (ReportLab) | Later | — |

### FR-11 Auth
| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-11.1 | Owner email/password login (bcrypt/argon2 hash), JWT bearer token | MVP | 1 |
| FR-11.2 | Passwordless demo-viewer login issuing a read-mostly token | MVP | 1 |
| FR-11.3 | All write endpoints require the owner role | MVP | 1 |

### FR-12 RAG / SOP retrieval
| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-12.1 | Lexical SOP search (Postgres full-text) restricted to the scenario's permitted documents | MVP | 2 |
| FR-12.2 | Original synthetic SOP corpus (no proprietary/scraped content) | MVP | 2 |
| FR-12.3 | Embedding retrieval (Gemini embeddings + pgvector), lexical fallback when not configured | Full | 10 |
| FR-12.4 | Evaluator checks that cited SOP IDs were actually retrieved in the run | MVP | 5 |

---

## 4. Non-functional requirements

| ID | Area | Requirement |
|---|---|---|
| NFR-01 | Security | Secrets only in env/deployment secret stores; `.env` git-ignored; `.env.example` with placeholders |
| NFR-02 | Security | CORS allowlist = deployed frontend origin(s) + localhost dev origin |
| NFR-03 | Security | Request body size limit (default 1 MB); rate limit on run creation and login |
| NFR-04 | Safety | Forbidden actions enforced in the backend tool policy layer, not only in prompts |
| NFR-05 | Safety | Customer messages, scenario text, tool results and SOPs are treated as untrusted data (prompt-injection aware) |
| NFR-06 | Privacy | Only synthetic data; PII-like fields (names, phones, emails, addresses) redacted in traces and reports |
| NFR-07 | Reliability | Graceful handling of model quota/rate-limit, timeout, malformed structured output, DB outage, tool errors; retries with exponential backoff only for transient errors |
| NFR-08 | Reproducibility | Each run stores scenario version, agent config snapshot, evaluator version, tool registry version, seed |
| NFR-09 | Honesty | No invented benchmark results; demo data labelled; cost shown only when usage metadata exists |
| NFR-10 | Performance | Budgets in [context/performance_review.md](context/performance_review.md) |
| NFR-11 | Cost | Runs on free tiers; CI never calls a paid or quota-limited LLM |
| NFR-12 | Observability | Structured JSON logs with `request_id` and `run_id` correlation; `/health` and `/version` endpoints |
| NFR-13 | Maintainability | Type hints everywhere, ruff clean, service logic separate from routes, no LLM calls in route functions, small modules |
| NFR-14 | Testability | Unit, integration, golden-agent and frontend tests per PROJECT.md §19; tests added with every evaluator/policy change |
| NFR-15 | Usability | Desktop-first responsive UI with loading/empty/error/success states; backend "waking up" state for cold starts |

## 5. Constraints

- Stack is fixed by PROJECT.md §12: React + Vite + TypeScript + Tailwind + shadcn/ui frontend; FastAPI + SQLAlchemy 2 + Alembic + LangGraph backend; PostgreSQL. No Next.js, no Streamlit, no Kubernetes/microservices.
- LLM: **Gemini Flash** (model ID from env `GEMINI_MODEL`). OpenAI is an optional adapter.
- Hosting: free tiers only — Vercel (frontend), Render free web service (backend; Hugging Face Spaces / Koyeb as fallbacks), Neon free Postgres.
- Free tiers have quotas, sleep/cold starts and changing terms; verify current limits before deploying.
- Gemini free tier may use submitted data to improve Google products — acceptable only because all data is synthetic.

## 6. Out of scope (MVP)

Live carrier integrations · real customer data · real refunds/reroutes/cancellations/notifications · autonomous production agent ·
agent marketplace · enterprise multi-tenancy · Kubernetes/microservices · model training · full supply-chain simulation.

---

## 7. Development environment requirements

| Item | Required version | Status on dev machine (2026-11-07) |
|---|---|---|
| Git | any recent | ✅ 2.55 |
| Python | **3.12.x** (3.14 is installed too but too new for some deps) | ✅ 3.12.10 |
| Node.js | 20 LTS or newer | ✅ 24.18 |
| npm | bundled with Node | ✅ 11.16 |
| WSL2 | required by Docker Desktop on Windows 11 Home | ❌ not installed — user installs (`wsl --install`, admin, reboot) |
| Docker Desktop + Compose v2 | recent | ❌ not installed — user installs (`winget install -e --id Docker.DockerDesktop`) |
| PostgreSQL 16 + pgvector | via Docker image `pgvector/pgvector:pg16`; fallback: Neon dev branch | pending Docker |

### Accounts needed (all free)

| Account | Used for | Who sets it up |
|---|---|---|
| GitHub | public repository + Actions CI | user |
| Google AI Studio | `GEMINI_API_KEY` (put in `backend/.env` yourself — never in chat or Git) | user |
| Vercel | frontend hosting | user (Phase 11) |
| Render | backend hosting | user (Phase 11) |
| Neon | managed Postgres | user (Phase 11, or earlier as Docker fallback) |

### Backend libraries (pinned in Phase 0 via lock file)
FastAPI, Uvicorn, Pydantic v2, pydantic-settings, SQLAlchemy 2, Alembic, psycopg 3 (binary), LangGraph,
langchain-core, langchain-google-genai (or google-genai), passlib/argon2 or bcrypt, PyJWT, httpx, pytest,
pytest-cov, ruff, mypy (optional). Later: pgvector (Python), ReportLab.

### Frontend libraries (pinned in Phase 0 via `package-lock.json`)
React, React DOM, Vite, TypeScript, Tailwind CSS, shadcn/ui (Radix), React Router, TanStack Query, Axios,
Recharts, Lucide React, a JSON editor component (Monaco or CodeMirror), Vitest + Testing Library,
ESLint, openapi-typescript (types generated from the backend OpenAPI schema).

---

## 8. Acceptance — Definition of Done (from PROJECT.md §25)

- [ ] A reviewer can open the deployed app
- [ ] Inspect a set of logistics scenarios
- [ ] Configure/select an agent
- [ ] Launch a benchmark (rule-based agent for viewers; Gemini for owner)
- [ ] Inspect tool calls and trace events
- [ ] See deterministic score breakdowns
- [ ] View evidence-linked failure diagnoses
- [ ] Compare two agent versions
- [ ] Export a report (JSON/CSV)
- [ ] Understand the benchmark methodology ([context/benchmark.md](context/benchmark.md))
- [ ] Reproduce the project locally using README
- [ ] See tests and green CI
- [ ] Understand limitations and what is simulated
