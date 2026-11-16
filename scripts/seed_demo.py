"""Create labelled demo data: the MVP suite run once with each rule-based agent.

Usage (from backend/, after seed_db.py):
    uv run python ../scripts/seed_demo.py

The runs are real (executed, traced, scored and diagnosed like any other) but marked
`is_demo = true`, so the dashboard and reports label them and can exclude them. No LLM is
called. Idempotent: an agent that already has a completed demo run of the suite is skipped.
Use this on a fresh deployment (Phase 11) so viewers see a populated dashboard.
"""

import sys

from sqlalchemy import select

from app.api.deps import Principal
from app.core.config import get_settings
from app.core.limits import SlidingWindowLimiter
from app.db.models import AgentConfig, BenchmarkSuite, SuiteRun
from app.db.session import get_sessionmaker
from app.services.benchmarks.service import SuiteService
from app.services.execution.executor import InlineExecutor
from app.services.execution.service import RunService

SUITE = "mvp-10"
AGENTS = ["rule-based-v1", "rule-based-v2-flawed"]
SEED_PRINCIPAL = Principal(subject="demo-seed", role="owner", email=None)


def main() -> int:
    settings = get_settings()
    session_factory = get_sessionmaker()
    with session_factory() as db:
        suite = db.scalar(select(BenchmarkSuite).where(BenchmarkSuite.name == SUITE))
        if suite is None:
            print(f"Suite {SUITE!r} not found: run seed_db.py first")
            return 1
        runs = RunService(
            db, settings, InlineExecutor(), session_factory, SlidingWindowLimiter(1000)
        )
        service = SuiteService(db, runs)
        for name in AGENTS:
            agent = db.scalars(
                select(AgentConfig)
                .where(AgentConfig.name == name, AgentConfig.status == "active")
                .order_by(AgentConfig.version.desc())
            ).first()
            if agent is None:
                print(f"skipped    {name}: agent config not found")
                continue
            existing = db.scalar(
                select(SuiteRun).where(
                    SuiteRun.suite_id == suite.id,
                    SuiteRun.agent_config_id == agent.id,
                    SuiteRun.is_demo,
                    SuiteRun.status == "completed",
                )
            )
            if existing is not None:
                print(f"unchanged  {name} v{agent.version}: demo suite run {existing.id}")
                continue
            suite_run = service.launch(suite.id, agent.id, 1, SEED_PRINCIPAL, is_demo=True)
            db.expire_all()
            suite_run = service.get_run(suite_run.id)
            rate = (suite_run.summary_json or {}).get("metrics", {}).get("task_success_rate")
            print(
                f"created    {name} v{agent.version}: demo suite run {suite_run.id} "
                f"({suite_run.status}, task success {rate})"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
