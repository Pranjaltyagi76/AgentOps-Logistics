# AgentOps Logistics

**A logistics-specific benchmark and reliability workbench for AI agents.**

AgentOps Logistics runs a candidate AI agent against reproducible logistics customer-support scenarios
(delayed shipments, missing scans, failed deliveries, SLA breaches, refund pressure…) using **mocked tools
and synthetic data**, records an observable execution trace, scores the run deterministically against
hidden ground truth, explains *where* the agent failed with cited evidence, and shows whether a new agent
version fixed failures or introduced regressions.

> **Project status:** 📐 Planning complete — **Phase 0 (Foundation) not started.**
> Nothing below marked *planned* exists yet. No benchmark results have been produced; none are shown here.

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
| Testing / CI | pytest, Vitest, ruff, GitHub Actions (no LLM calls in CI) |
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

## Repository layout (planned)

```text
agentops-logistics/
├── frontend/            React + Vite app            (planned — Phase 0)
├── backend/             FastAPI app, agent, tools   (planned — Phase 0)
├── data/
│   ├── scenarios/       versioned scenario JSON     (planned — Phase 1)
│   └── sops/            synthetic SOP documents     (planned — Phase 2)
├── scripts/             seed, validate, run_benchmark (planned)
├── context/             design & planning docs      ✅
├── .github/workflows/   CI                          (planned — Phase 0)
├── docker-compose.yml   local Postgres              (planned — Phase 0)
├── PROJECT.md           ✅
├── requirement.md       ✅
└── README.md            ✅
```

## Getting started

> Commands become real in Phase 0; this section will be updated then.

**Prerequisites:** Git, Python 3.12, Node.js 20+, Docker Desktop (Windows needs WSL2). See
[requirement.md §7](requirement.md) and [context/deployment.md](context/deployment.md).

Planned local workflow:

```powershell
docker compose up -d db                      # Postgres 16 + pgvector
cd backend
py -3.12 -m venv .venv; .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env                  # add GEMINI_API_KEY yourself (optional)
alembic upgrade head; python ..\scripts\seed_db.py
uvicorn app.main:app --reload                # then, in a 2nd terminal:
cd frontend; npm install; npm run dev
```

Full step-by-step instructions: [context/deployment.md §2](context/deployment.md).

Without a Gemini key the app still works using the rule-based agents.

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
