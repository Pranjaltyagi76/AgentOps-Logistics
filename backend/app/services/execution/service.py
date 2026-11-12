"""Creating, listing, inspecting and cancelling runs; startup sweeper; daily usage counters."""

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import partial

from sqlalchemy import func, select, text, tuple_, update
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.config import Settings
from app.core.errors import AppError
from app.core.limits import SlidingWindowLimiter
from app.db.models import AgentConfig, Run, Scenario, TraceEvent
from app.domain.policy import POLICY_VERSION
from app.domain.taxonomy import TAXONOMY_VERSION
from app.schemas.agent_config import AgentConfigSpec
from app.services.evaluation.service import evaluate_run_safely
from app.services.execution.collector import SessionFactory, TraceCollector
from app.services.execution.executor import RunExecutor
from app.services.execution.worker import execute_run, mark_overrun
from app.services.providers.factory import provider_problem, resolve_model_id
from app.services.tools.registry import TOOL_REGISTRY_VERSION

LLM_RUNS_KEY = "llm_runs"
MAX_PAGE = 100


class RunNotFoundError(AppError):
    status_code = 404
    code = "run_not_found"


class RunConflictError(AppError):
    status_code = 409
    code = "run_conflict"


@dataclass(frozen=True)
class RunFilters:
    status: str | None = None
    scenario_key: str | None = None
    agent_name: str | None = None


def _encode_cursor(run: Run) -> str:
    raw = f"{run.created_at.isoformat()}|{run.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        created, run_id = raw.split("|")
        return datetime.fromisoformat(created), uuid.UUID(run_id)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise AppError("Invalid cursor", code="invalid_cursor") from exc


def try_consume(db: Session, key: str, limit: int, day: date | None = None) -> bool:
    """Atomically increments today's counter unless it already reached `limit`."""
    day = day or datetime.now(UTC).date()
    row = db.execute(
        text(
            "INSERT INTO usage_counters (id, day, key, count) VALUES (:id, :day, :key, 1) "
            "ON CONFLICT (day, key) DO UPDATE SET count = usage_counters.count + 1 "
            "WHERE usage_counters.count < :limit RETURNING count"
        ),
        {"id": uuid.uuid4(), "day": day, "key": key, "limit": limit},
    ).first()
    return row is not None and (row[0] <= limit)


def usage_today(db: Session, key: str, day: date | None = None) -> int:
    day = day or datetime.now(UTC).date()
    count = db.scalar(
        text("SELECT count FROM usage_counters WHERE day = :day AND key = :key"),
        {"day": day, "key": key},
    )
    return int(count or 0)


def sweep_orphaned_runs(session_factory: SessionFactory) -> int:
    """Marks runs left queued/running by a restart as errored (decision D-10)."""
    with session_factory() as db:
        orphans = list(db.scalars(select(Run).where(Run.status.in_(("queued", "running")))))
        now = datetime.now(UTC)
        error = {"code": "orphaned", "message": "The server restarted before this run finished"}
        for run in orphans:
            run.status = "errored"
            run.error_kind = "infra"
            run.error_json = error
            run.finished_at = now
        db.commit()
        last_seqs = (
            {
                run_id: seq
                for run_id, seq in db.execute(
                    select(TraceEvent.run_id, func.max(TraceEvent.seq))
                    .where(TraceEvent.run_id.in_([r.id for r in orphans]))
                    .group_by(TraceEvent.run_id)
                )
            }
            if orphans
            else {}
        )
    for run in orphans:
        TraceCollector(run.id, session_factory, start_seq=last_seqs.get(run.id, 0)).emit(
            "run_error", error=error
        )
        evaluate_run_safely(session_factory, run.id)  # verdict ERROR: excluded from metrics
    return len(orphans)


class RunService:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        executor: RunExecutor,
        session_factory: SessionFactory,
        limiter: SlidingWindowLimiter,
    ) -> None:
        self.db = db
        self.settings = settings
        self.executor = executor
        self.session_factory = session_factory
        self.limiter = limiter

    # --- create --------------------------------------------------------------------------

    def create(self, scenario_id: uuid.UUID, agent_id: uuid.UUID, principal: Principal) -> Run:
        scenario = self.db.get(Scenario, scenario_id)
        if scenario is None:
            raise AppError("Scenario not found", code="scenario_not_found", status_code=404)
        if scenario.status == "archived":
            raise RunConflictError("This scenario is archived", code="scenario_archived")
        agent = self.db.get(AgentConfig, agent_id)
        if agent is None:
            raise AppError("Agent config not found", code="agent_not_found", status_code=404)
        if agent.status == "archived":
            raise RunConflictError("This agent config is archived", code="agent_archived")
        config = AgentConfigSpec.model_validate(agent.config_json)

        if config.is_llm:
            if not principal.is_owner:
                raise AppError(
                    "The demo viewer can only run rule-based agents",
                    code="forbidden",
                    status_code=403,
                )
            problem = provider_problem(config, self.settings)
            if problem is not None:
                code = (
                    "provider_not_configured"
                    if config.provider == "gemini"
                    else "provider_not_available"
                )
                raise RunConflictError(problem, code=code)
        if not self.limiter.allow(f"runs:{principal.subject}"):
            raise AppError(
                "Too many runs started; wait a minute", code="rate_limited", status_code=429
            )
        active = self.db.scalar(
            select(func.count()).select_from(Run).where(Run.status.in_(("queued", "running")))
        )
        if (active or 0) >= self.settings.max_queued_runs:
            raise AppError(
                "The run queue is full; try again shortly", code="run_queue_full", status_code=429
            )

        # Counted last, so a launch rejected for another reason never uses up the daily cap.
        if config.is_llm and not try_consume(
            self.db, LLM_RUNS_KEY, self.settings.llm_daily_run_cap
        ):
            self.db.rollback()
            raise AppError(
                f"The daily limit of {self.settings.llm_daily_run_cap} LLM runs is used up; "
                "it resets at 00:00 UTC",
                code="llm_daily_cap_reached",
                status_code=429,
            )

        # The exact versions used are frozen from now on (edits create new versions).
        scenario.is_locked = True
        agent.is_locked = True
        run = Run(
            scenario_id=scenario.id,
            agent_config_id=agent.id,
            scenario_key=scenario.scenario_key,
            scenario_version=scenario.version,
            agent_name=agent.name,
            agent_version=agent.version,
            provider=agent.provider,
            status="queued",
            config_snapshot_json=agent.config_json,
            versions_json={
                "tool_registry": TOOL_REGISTRY_VERSION,
                "policy": POLICY_VERSION,
                "taxonomy": TAXONOMY_VERSION,
                "prompt": config.prompt_version,
                "model": resolve_model_id(config, self.settings),
                "evaluator": None,  # set in Phase 5
            },
            triggered_by_role=principal.role,
            triggered_by=principal.subject,
        )
        self.db.add(run)
        self.db.commit()
        self.executor.submit(
            run.id,
            partial(self._job, run.id),
            timeout_s=float(config.timeout_s),
            on_overrun=partial(mark_overrun, run.id, self.session_factory),
        )
        self.db.refresh(run)
        return run

    def _job(self, run_id: uuid.UUID, token) -> None:  # type: ignore[no-untyped-def]
        execute_run(run_id, token, self.session_factory, self.settings)

    # --- read ----------------------------------------------------------------------------

    def get(self, run_id: uuid.UUID) -> Run:
        run = self.db.get(Run, run_id)
        if run is None:
            raise RunNotFoundError("Run not found")
        return run

    def list_page(
        self, filters: RunFilters, *, limit: int = 25, cursor: str | None = None
    ) -> tuple[list[Run], str | None]:
        query = select(Run)
        if filters.status:
            query = query.where(Run.status == filters.status)
        if filters.scenario_key:
            query = query.where(Run.scenario_key == filters.scenario_key)
        if filters.agent_name:
            query = query.where(Run.agent_name == filters.agent_name)
        if cursor:
            created, run_id = _decode_cursor(cursor)
            query = query.where(tuple_(Run.created_at, Run.id) < tuple_(created, run_id))
        limit = max(1, min(limit, MAX_PAGE))
        rows = list(
            self.db.scalars(query.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit + 1))
        )
        next_cursor = _encode_cursor(rows[limit - 1]) if len(rows) > limit else None
        return rows[:limit], next_cursor

    def trace(self, run_id: uuid.UUID, after_seq: int = 0) -> list[TraceEvent]:
        self.get(run_id)
        return list(
            self.db.scalars(
                select(TraceEvent)
                .where(TraceEvent.run_id == run_id, TraceEvent.seq > after_seq)
                .order_by(TraceEvent.seq)
            )
        )

    def trace_count(self, run_id: uuid.UUID) -> int:
        return (
            self.db.scalar(
                select(func.count()).select_from(TraceEvent).where(TraceEvent.run_id == run_id)
            )
            or 0
        )

    # --- cancel --------------------------------------------------------------------------

    def cancel(self, run_id: uuid.UUID, principal: Principal) -> Run:
        run = self.get(run_id)
        if not principal.is_owner and run.triggered_by != principal.subject:
            raise AppError(
                "You can only cancel runs you started", code="forbidden", status_code=403
            )
        if not run.is_active:
            raise RunConflictError(f"Run is already {run.status}", code="run_not_active")
        self.db.execute(update(Run).where(Run.id == run_id).values(cancel_requested=True))
        cancelled_now = self.db.execute(
            update(Run)
            .where(Run.id == run_id, Run.status == "queued")
            .values(status="cancelled", stop_reason="cancelled", finished_at=datetime.now(UTC))
        ).rowcount  # type: ignore[attr-defined]
        self.db.commit()
        self.executor.cancel(run_id, "cancelled")
        if cancelled_now:
            last = self.trace_count(run_id)
            TraceCollector(run_id, self.session_factory, start_seq=last).emit(
                "run_finished", output={"status": "cancelled", "stop_reason": "cancelled"}
            )
        self.db.refresh(run)
        return run
