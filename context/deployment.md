# Deployment — AgentOps Logistics

> Local development setup, environment variables, and the free-tier production/demo topology.
> **Free-tier limits and terms change — verify each provider's current pricing page before deploying.**
> Figures below marked "verify" are indicative, not guaranteed.
>
> Last updated: 2026-11-07 (planning; nothing deployed yet).

---

## 1. Topology

```text
 Browser ──HTTPS──▶ Vercel (static React build)
    │
    └──HTTPS /api/v1 (JWT bearer, CORS allowlist)──▶ Render free web service (FastAPI, 1 instance)
                                                        │  ├─▶ Gemini API (GEMINI_API_KEY, server-side only)
                                                        │
                                                        └──TLS──▶ Neon free Postgres (pooled connection)
```

| Component | Primary (free) | Fallback | Notes |
|---|---|---|---|
| Frontend | Vercel Hobby | Netlify / Cloudflare Pages | static SPA; personal/non-commercial use terms |
| Backend | Render free web service | Hugging Face Spaces (Docker), Koyeb free | free instances sleep when idle → cold start |
| Database | Neon free | Supabase free | both support pgvector; Neon autosuspends compute when idle |
| LLM | Gemini Flash (Google AI Studio key) | — (rule-based agents need no LLM) | free-tier quota, RPM limits, data-use terms apply |
| CI | GitHub Actions (public repo) | — | no LLM calls |

## 2. Local development

### 2.1 Prerequisites (one-time, Windows 11 Home)

Run in an **Administrator PowerShell** (the user does this; it changes Windows features and needs a reboot):

```bash
wsl --install
```

Reboot, then:

```bash
winget install -e --id Docker.DockerDesktop
```

Start Docker Desktop once and accept its setup. Verify:

```bash
docker compose version
```

**Fallbacks without Docker:**
- **Neon:** create a free project, make a `dev` branch, and put its connection string in `backend/.env` as `DATABASE_URL`.
- **Portable Postgres binaries** (what the dev machine uses as of 2026-11-08, no admin rights needed):
  Postgres 16.2 binaries in `%LOCALAPPDATA%\Programs\pgsql-16`, data in `%LOCALAPPDATA%\agentops-pg\data`,
  listening on `127.0.0.1:5432` with the same user/password/database names as the Docker setup, plus an
  empty `agentops_test` database for tests. Start it after a reboot with:

```powershell
& "$env:LOCALAPPDATA\Programs\pgsql-16\bin\pg_ctl.exe" -D "$env:LOCALAPPDATA\agentops-pg\data" -l "$env:LOCALAPPDATA\agentops-pg\server.log" -o "-p 5432 -c listen_addresses=127.0.0.1" start
```

### 2.2 Run locally (available from Phase 0)

```bash
docker compose up -d db
```

Backend (PowerShell, from the repo root). Python dependencies are managed by **uv**: `uv sync`
creates `backend/.venv` from the exact versions in `backend/uv.lock`.

```powershell
cd backend
uv sync
Copy-Item .env.example .env     # then edit values; add GEMINI_API_KEY yourself (Phase 6)
uv run alembic upgrade head
uv run python ..\scripts\seed_db.py         # loads data/scenarios (safe to re-run)
uv run python ..\scripts\create_owner.py    # reads OWNER_EMAIL / OWNER_PASSWORD from env or .env
uv run uvicorn app.main:app --reload --port 8000
```

To add a dependency: `uv add <package>` (or `uv add --dev <package>`), then commit `pyproject.toml` and `uv.lock`.

Frontend (second terminal, from the repo root):

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local  # VITE_API_BASE_URL=http://localhost:8000
npm run dev                     # http://localhost:5173
```

### 2.3 Local database

[../docker-compose.yml](../docker-compose.yml) runs `pgvector/pgvector:pg16` as `agentops-db` on port 5432
(user `agentops`, password `agentops_dev`, database `agentops`, for local use only) with a named volume
and a `pg_isready` healthcheck. The default `DATABASE_URL` points at `127.0.0.1` rather than
`localhost`, so a missing database fails fast instead of timing out on IPv6 first.

### 2.4 Checks

| Area | Commands |
|---|---|
| Backend | `uv run ruff check .` · `uv run ruff format --check .` · `uv run python ../scripts/validate_scenarios.py` · `uv run pytest` |
| Backend + real DB | set `RUN_DB_TESTS=1` and `TEST_DATABASE_URL` (an empty database, e.g. `.../agentops_test`), then `uv run pytest`; each test is rolled back |
| Frontend | `npm run lint` (oxlint) · `npm run typecheck` · `npm test` (Vitest) · `npm run build` |

## 3. Environment variables

### Backend (`backend/.env`, Render env settings)

| Variable | Required | Example / default | Notes |
|---|---|---|---|
| `APP_ENV` | yes | `local` \| `production` | toggles docs exposure, log format |
| `DATABASE_URL` | yes | `postgresql+psycopg://agentops:agentops_dev@localhost:5432/agentops` | Neon: use the **pooled** host, `?sslmode=require` |
| `MIGRATION_DATABASE_URL` | no | Neon **direct** (non-pooled) URL | Alembic uses it if set (DDL through PgBouncer can misbehave) |
| `TEST_DATABASE_URL` | tests only | `.../agentops_test` | empty database used by `db`-marked tests; never point it at real data |
| `JWT_SECRET` | yes in production | random 32+ bytes | `python -c "import secrets;print(secrets.token_urlsafe(48))"`; production refuses to start with the dev default |
| `JWT_EXPIRE_MINUTES` | no | `120` | |
| `LOGIN_RATE_LIMIT_PER_MINUTE` | no | `10` | per client IP, in memory |
| `DATA_DIR` | no | repo `data/` | scenarios and SOP catalog location |
| `OWNER_EMAIL` / `OWNER_PASSWORD` | for `create_owner` | — | used once by the script; do not keep the password in prod env afterwards |
| `DEMO_LOGIN_ENABLED` | no | `true` | passwordless viewer tokens |
| `CORS_ORIGINS` | yes | `http://localhost:5173` | prod: `https://<app>.vercel.app` (comma-separated) |
| `GEMINI_API_KEY` | no | — | **never commit**; absent ⇒ LLM agents "not configured" |
| `GEMINI_MODEL` | no | `gemini-3.5-flash` | used by configs with `model_id: "default"`; check AI Studio for current IDs |
| `GEMINI_THINKING_LEVEL` | no | `minimal` | Gemini 3+ only (`minimal`/`low`/…); 2.5 models get `thinking_budget=0` |
| `GEMINI_RPM_LIMIT` | no | `5` | process-wide request throttle; keep below the free-tier per-minute limit |
| `GEMINI_REQUEST_TIMEOUT_S` | no | `20` | per request, min 10 (Gemini's minimum); a hung request is retried |
| `LLM_DAILY_RUN_CAP` | no | `50` | |
| `MAX_CONCURRENT_RUNS` | no | `2` | thread-pool size; more runs wait in the queue |
| `MAX_QUEUED_RUNS` | no | `20` | queued + running cap (429 beyond it) |
| `RUN_RATE_LIMIT_PER_MINUTE` | no | `10` | per principal (all demo viewers share one) |
| `RUN_WATCHDOG_GRACE_S` | no | `15` | extra time before a stuck run is marked timed out |
| `SWEEP_ORPHANED_RUNS_ON_STARTUP` | no | `true` | marks runs interrupted by a restart as orphaned |
| `MAX_REQUEST_BYTES` | no | `1000000` | request body limit (413) |
| `RUN_TIMEOUT_SECONDS` | no | `60` | rule-based runs use 10 |
| `MAX_AGENT_STEPS` / `MAX_TOOL_CALLS` | no | `8` / `10` | |
| `LLM_JUDGE_ENABLED` | no | `false` | |
| `LOG_LEVEL` | no | `INFO` | |
| `OPENAI_API_KEY` | no | — | optional adapter (Later) |

### Frontend (`frontend/.env.local`, Vercel env settings)

| Variable | Example | Notes |
|---|---|---|
| `VITE_API_BASE_URL` | `https://agentops-api.onrender.com` | baked in at build time — **never put secrets in `VITE_*`** |

Commit only `.env.example` files with placeholders.

## 4. Database (Neon)

1. Create project `agentops-logistics` (choose the region nearest the Render region).
2. Ensure extension availability: `CREATE EXTENSION IF NOT EXISTS vector;` (done by an Alembic migration in Phase 10; harmless earlier).
3. Copy both the **pooled** connection string (→ `DATABASE_URL`) and the **direct** one (→ `MIGRATION_DATABASE_URL`).
4. SQLAlchemy engine: `pool_pre_ping=True`, small pool (`pool_size=3`, `max_overflow=2`), `pool_recycle=300` — compute autosuspends when idle and the first query after wake is slower.
5. Storage is limited on the free tier (verify; historically ~0.5 GB). See trace retention in [system_design.md §11](system_design.md).

## 5. Backend (Render)

1. New **Web Service** from the GitHub repo, root directory `backend`, runtime Python (or Docker using `backend/Dockerfile`).
2. Build command: `pip install uv && uv sync --locked --no-dev` (or deploy `backend/Dockerfile`; decided in Phase 11)
3. Start command:
   ```bash
   alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers
   ```
   (Single instance, so running migrations at start is acceptable.)
4. Health check path: `/api/v1/health`.
5. Set env vars from §3 (`APP_ENV=production`, secrets as secret values).
6. One-time: run `python ../scripts/seed_db.py` and `python ../scripts/create_owner.py` from a Render shell (working dir `backend`), or run them locally with `DATABASE_URL` pointed at Neon.

**Free-tier realities (verify):** instance spins down after ~15 min without traffic; cold start can take up to about a minute; limited RAM (~512 MB). Consequences:
- Frontend shows a "waking up backend…" banner and retries.
- In-flight runs die on spin-down → startup sweeper marks them `errored(orphaned)`.
- Avoid heavy local ML libraries (e.g. sentence-transformers) on this instance; use Gemini embeddings or lexical search.
- Do **not** add keep-alive pinging to defeat sleep; accept cold starts or move to a paid/VPS plan.

## 6. Frontend (Vercel)

1. Import the GitHub repo, root directory `frontend`, framework preset Vite.
2. Build `npm run build`, output `dist`.
3. Env: `VITE_API_BASE_URL` = Render URL.
4. SPA routing — `frontend/vercel.json`:
   ```json
   { "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }] }
   ```
5. After the first deploy, add the Vercel production URL to backend `CORS_ORIGINS` and redeploy the backend.

## 7. CI/CD

- GitHub Actions on push/PR: backend (ruff, pytest with `pgvector/pgvector:pg16` service container), frontend (oxlint, `tsc -b`, vitest, build); scenario validation added in Phase 1.
- Render and Vercel auto-deploy from `main` after CI passes (enable "wait for CI" / branch protection).
- No secrets needed in CI; LLM tests are skipped.

## 8. Smoke test (after each deploy)

1. `GET <api>/api/v1/health` → `{"status":"ok","db":"ok"}`
2. `GET <api>/api/v1/version` → expected git SHA
3. Open the Vercel URL → demo login → scenario list shows 10+ scenarios
4. Launch `rule-based-v1` on one scenario → completed, trace + evaluation visible
5. Owner login → launch one Gemini run (counts against the daily cap) → completed or a clear quota message
6. Restart the backend service → previous run, trace and score still present
7. Browser devtools: no API key in bundle or network responses; CORS rejects another origin

## 9. Deployment checklist (PROJECT.md §20.4)

- [ ] frontend build succeeds
- [ ] backend health endpoint works
- [ ] database is reachable
- [ ] migrations run successfully
- [ ] seed scenarios load
- [ ] model key configured server-side
- [ ] CORS allows only the deployed frontend (+ localhost for dev builds only)
- [ ] run limits, daily LLM cap and timeouts configured
- [ ] demo login and owner login work
- [ ] one scenario executes end-to-end
- [ ] trace and score persist after restart
- [ ] no secrets in Git or browser bundle
- [ ] README includes live URLs and demo limitations

## 10. Rollback and operations

- Vercel: promote the previous deployment.
- Render: redeploy the previous commit. Migrations are additive, so older code tolerates the newer schema; never ship a destructive migration together with code that needs it.
- Neon: point-in-time restore / branch from a past timestamp if data is damaged (verify retention window on free tier).
- Rotate `GEMINI_API_KEY` / `JWT_SECRET` in Render env; rotating `JWT_SECRET` logs everyone out.
- Watch Gemini usage in AI Studio and the `usage_counters` table.
