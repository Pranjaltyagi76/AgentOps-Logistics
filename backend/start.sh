#!/bin/sh
# Container start (Phase 11). Render's free tier has no shell or one-off jobs, so the one-time
# steps run here on every boot; each is idempotent and calls no LLM.
#
# Free instances sleep when idle and every wake-up runs this script, so only the migrations
# run before the server starts. Seeding (a no-op once the data is current) runs alongside it,
# which keeps the cold start short; on a first deploy the data appears a few seconds later.
set -e

echo "start: migrations"
alembic upgrade head

seed() {
  echo "start: seed scenarios, SOPs, agents and suites"
  python ../scripts/seed_db.py
  if [ "${SEED_DEMO_ON_START:-true}" = "true" ]; then
    echo "start: demo suite runs (skipped when they exist)"
    python ../scripts/seed_demo.py
  fi
  if [ -n "${OWNER_PASSWORD:-}" ]; then
    # Creates the owner (or resets its password). Remove OWNER_PASSWORD after the first boot.
    echo "start: owner account"
    python ../scripts/create_owner.py
  fi
  echo "start: seeding done"
}
seed &

echo "start: serving on port ${PORT:-8000}"
# --no-proxy-headers: the client IP comes from CLIENT_IP_HEADER / TRUSTED_PROXY_HOPS
# (app/core/limits.py), not from uvicorn.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --no-server-header --no-proxy-headers
