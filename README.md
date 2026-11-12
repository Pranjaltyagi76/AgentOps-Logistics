# AgentOps Logistics

**A logistics-specific benchmark and reliability workbench for AI agents.**

AgentOps Logistics runs a candidate AI agent against reproducible logistics customer-support scenarios
(delayed shipments, missing scans, failed deliveries, SLA breaches, refund pressure…) using **mocked tools
and synthetic data**, records an observable execution trace, scores the run deterministically against
hidden ground truth, explains *where* the agent failed with cited evidence, and shows whether a new agent
version fixed failures or introduced regressions.

> **Project status:** 🏗️ **Phase 6 done**: the same agent graph can now be driven by Gemini Flash (owner only,
> daily-capped and throttled, no thought content stored, provider failures reported as platform errors).
> Earlier: every finished run is scored deterministically (weighted 0–100,
> four hard safety gates, verdict) with each check linked to the trace step behind it (Phase 5); runs
> with a background executor and a live trace viewer (Phase 4), a LangGraph agent with
> two rule-based baselines and versioned agent configs (Phase 3), 10 validated scenarios, owner/demo login and catalog UI (Phase 1),
> plus 10 mock logistics tools behind a policy-enforcing gateway, 7 synthetic SOPs with Postgres full-text
> search, and reproducible fault injection (Phase 2). Next: failure diagnosis (Phase 7).
> Features below are *planned* unless marked otherwise. Benchmark results so far are for the rule-based
> baselines (context/benchmark.md §15); Gemini has only smoke-tested single runs, not a benchmark.

---

## What it is / what it is not

| It is | It is not |
|---|---|
| A testing and reliability workbench for logistics AI agents | A shipment-management or carrier system |
| Deterministic, auditable scoring with hard safety gates | A single opaque "LLM says 8/10" score |
| A focused portfolio project | Production-ready or a replacement for commercial agent platforms |
| Fully simulated: mock tools, synthetic shipments and SOPs | Connected to any real carrier, customer, refund or messaging system |

## Planned features

- **Scenario benchmark** — versioned JSON scenarios with hidden ground truth (root-cause label, required evidence IDs, required/forbidden actions, escalation expectation).
- **Controlled execution** — a LangGraph agent calls Pydantic-validated mock tools; forbidden actions are blocked by a backend policy layer.
- **Trace capture** — every node transition and tool call with arguments, results, timing, and token usage when the provider reports it. No chain-of-thought is stored.
- **Deterministic evaluation** — weighted 0–100 score plus safety gates that a high score can never hide.
- **Failure diagnosis** — failure type, severity, stage and debugging direction, each citing trace events — or `insufficient_evidence`.
- **Regression testing** — run a suite with agent version B, compare with version A: newly failed, fixed, safety regressions, latency/cost deltas.
- **Dashboard & reports** — KPIs from persisted runs only; JSON/CSV export.
- **No-LLM mode** — rule-based agents let anyone run the full pipeline without an API key.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React, Vite, TypeScript, Tailwind CSS, shadcn/ui, React Router, TanStack Query, Recharts, Lucide |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg 3, LangGraph |
| Database | PostgreSQL 16 (+ pgvector later for SOP retrieval) |
| LLM | Google Gemini Flash (server-side key); optional OpenAI adapter |
| Tooling | uv (Python deps + lockfile), npm, ruff, oxlint |
| Testing / CI | pytest, Vitest + Testing Library, GitHub Actions (no LLM calls in CI) |
| Hosting (free tiers) | Vercel (frontend), Render (backend), Neon (Postgres) |

## Documentation map

| Document | What it covers |
|---|---|
| [PROJECT.md](PROJECT.md) | Original product + engineering specification — **source of truth** |
| [requirement.md](requirement.md) | Numbered functional / non-functional requirements, environment and accounts |
| [context/system_design.md](context/system_design.md) | Design decisions, core flows, run lifecycle, failure handling, security model |
| [context/architecture.md](context/architecture.md) | Modules, interfaces, data model, API, trace schema, frontend structure |
| [context/phasewise_roadmap.md](context/phasewise_roadmap.md) | Phases 0–12 with tasks, acceptance criteria and status |
| [context/benchmark.md](context/benchmark.md) | Scenario taxonomy, root-cause labels, evidence IDs, scoring, gates, metrics |
| [context/performance_review.md](context/performance_review.md) | Performance and cost budgets, how to measure, review log |
| [context/deployment.md](context/deployment.md) | Local setup, environment variables, Vercel/Render/Neon deployment, checklist |

The `context/` folder is the working knowledge base used throughout development; keep it updated as the
implementation evolves.

## Repository layout

```text
agentops-logistics/
├── backend/             FastAPI app (uv project, Alembic migrations, pytest)   ✅ Phase 0
├── frontend/            React + Vite + TypeScript app (Tailwind, shadcn/ui)    ✅ Phase 0
├── data/
│   ├── scenarios/       10 versioned scenario JSON files                        ✅ Phase 1
│   ├── sops/            7 synthetic SOP documents + section catalog          ✅ Phase 2
│   └── agents/          rule-based + Gemini agent configs                      ✅ Phase 3, 6
├── scripts/             validate_scenarios, seed_db, create_owner, run_agent, evaluate_runs, perf_probe ✅
├── context/             design & planning docs      ✅
├── .github/workflows/   CI (backend + frontend)     ✅ Phase 0
├── docker-compose.yml   local Postgres 16 + pgvector ✅ Phase 0
├── PROJECT.md           ✅
├── requirement.md       ✅
└── README.md            ✅
```

## Getting started

**Prerequisites:** Git, Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 22+ (CI uses 24), and
Docker Desktop for the local database (Windows needs WSL2), or a free Neon Postgres URL instead.
See [requirement.md §7](requirement.md) and [context/deployment.md](context/deployment.md).

**1. Database**

```powershell
docker compose up -d db
```

**2. Backend** (from the repo root) at http://localhost:8000, API docs at `/docs`

```powershell
cd backend
uv sync
Copy-Item .env.example .env        # set JWT_SECRET, OWNER_EMAIL, OWNER_PASSWORD
uv run alembic upgrade head
uv run python ..\scripts\seed_db.py
uv run python ..\scripts\create_owner.py
uv run uvicorn app.main:app --reload --port 8000
```

**3. Frontend** (second terminal, from the repo root) at http://localhost:5173

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev
```

Sign in with the owner account, or click **Continue as demo viewer** for read-only access (hidden
answers stay hidden). **System status** in the sidebar shows whether the API and database are reachable.

**Checks** (the same ones CI runs):

```powershell
cd backend; uv run ruff check .; uv run ruff format --check .; uv run python ..\scripts\validate_scenarios.py; uv run pytest
```

```powershell
cd frontend; npm run lint; npm run typecheck; npm test; npm run build
```

Database-backed tests run only with `RUN_DB_TESTS=1`. They use `TEST_DATABASE_URL` (a separate, empty
database) if set, otherwise `DATABASE_URL`; each test is rolled back. CI provides a Postgres service.
Full step-by-step instructions: [context/deployment.md §2](context/deployment.md).

## Development workflow

Work is done **phase by phase** ([context/phasewise_roadmap.md](context/phasewise_roadmap.md)). Each phase
starts with a short plan (files to change + acceptance criteria), is approved, implemented with tests, and
leaves the app runnable. See PROJECT.md §24 for the rules.

## Limitations (by design)

- All logistics data, tools, carriers and SOPs are synthetic; all "write" actions are simulated.
- Free-tier hosting: the backend sleeps when idle, so the first request can take up to about a minute.
- LLM-backed runs are capped per day to stay inside the Gemini free-tier quota.
- LLM outputs are non-deterministic even at temperature 0; repeat runs may differ.

## License

To be decided.
