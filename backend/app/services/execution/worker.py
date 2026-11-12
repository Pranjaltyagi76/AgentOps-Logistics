"""The job that executes one run: load, mark running, run the agent, record the result.

Status updates are compare-and-set (`WHERE status = ...`), so a run that the watchdog or a
cancel has already finalised is never overwritten by a late result.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update

from app.core.config import Settings, get_settings
from app.db.models import Run, Scenario
from app.schemas.agent_config import AgentConfigSpec
from app.schemas.scenario import ScenarioSpec
from app.services.agent_graph.graph import AgentRunResult, RunHooks
from app.services.agent_graph.runner import run_scenario
from app.services.benchmarks.settle import mark_suite_started, settle_for_run
from app.services.evaluation.service import evaluate_run_safely
from app.services.execution.collector import SessionFactory, TraceCollector
from app.services.execution.executor import CancelToken
from app.services.providers.errors import ProviderError
from app.services.providers.factory import resolve_model_id
from app.services.sops.service import PerCallSopSearcher

logger = logging.getLogger(__name__)

# Agent stop reason -> (run status, error kind)
_STATUS_FOR_STOP: dict[str, tuple[str, str | None]] = {
    "completed": ("completed", None),
    "step_limit": ("completed", None),  # the agent ran out of steps: an agent failure, scored later
    "timeout": ("timed_out", "agent"),
    "cancelled": ("cancelled", None),
    "malformed_output": ("errored", "agent"),
    "agent_error": ("errored", "agent"),
    "provider_error": ("errored", "infra"),  # quota / outage / auth: excluded from agent metrics
}


def _now() -> datetime:
    return datetime.now(UTC)


def _finish(
    session_factory: SessionFactory, run_id: uuid.UUID, from_status: str, **values: Any
) -> bool:
    with session_factory() as db:
        result = db.execute(
            update(Run).where(Run.id == run_id, Run.status == from_status).values(**values)
        )
        db.commit()
        return bool(result.rowcount)  # type: ignore[attr-defined]


def _usage_summary(result: AgentRunResult) -> dict[str, Any] | None:
    if not result.usage:
        return None

    def total(key: str) -> int | None:
        values = [u.get(key) for u in result.usage]
        return (
            sum(v for v in values if v is not None) if all(v is not None for v in values) else None
        )

    return {
        "model_calls": len(result.usage),
        "input_tokens": total("input_tokens"),
        "output_tokens": total("output_tokens"),
        "thinking_tokens": total("thinking_tokens"),
    }


def _error_json(result: AgentRunResult) -> dict[str, Any]:
    if result.stop_reason == "provider_error" and result.errors:
        last = result.errors[-1]
        return {
            "code": last.get("code", "provider_error"),
            "message": last.get("message"),
            "status": last.get("status"),
            "errors": result.errors,
        }
    return {"code": result.stop_reason, "errors": result.errors}


def mark_overrun(run_id: uuid.UUID, session_factory: SessionFactory) -> None:
    """Watchdog callback: the run blew past its limit (e.g. a stuck call)."""
    finished = _now()
    if _finish(
        session_factory,
        run_id,
        "running",
        status="timed_out",
        stop_reason="timeout",
        error_kind="agent",
        error_json={"code": "watchdog_timeout", "message": "Run exceeded its time limit"},
        finished_at=finished,
    ):
        logger.warning("Run %s marked timed out by the watchdog", run_id)
        evaluate_run_safely(session_factory, run_id)
        settle_for_run(session_factory, run_id)


def execute_run(
    run_id: uuid.UUID,
    token: CancelToken,
    session_factory: SessionFactory,
    settings: Settings | None = None,
) -> None:
    try:
        _execute_run(run_id, token, session_factory, settings or get_settings())
    finally:
        settle_for_run(session_factory, run_id)  # completes its suite run when it was the last


def _execute_run(
    run_id: uuid.UUID,
    token: CancelToken,
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    with session_factory() as db:
        run = db.get(Run, run_id)
        if run is None:
            return
        if token.is_set or run.cancel_requested:
            db.execute(
                update(Run)
                .where(Run.id == run_id, Run.status == "queued")
                .values(status="cancelled", stop_reason="cancelled", finished_at=_now())
            )
            db.commit()
            return
        started_at = _now()
        claimed = db.execute(
            update(Run)
            .where(Run.id == run_id, Run.status == "queued")
            .values(status="running", started_at=started_at)
        ).rowcount  # type: ignore[attr-defined]
        if claimed and run.suite_run_id is not None:
            mark_suite_started(db, run.suite_run_id)
        db.commit()
        if not claimed:
            return
        scenario_row = db.get(Scenario, run.scenario_id)
        assert scenario_row is not None
        scenario = ScenarioSpec.model_validate(scenario_row.scenario_json)
        config = AgentConfigSpec.model_validate(run.config_snapshot_json)

    collector = TraceCollector(run_id, session_factory)
    collector.emit(
        "run_started",
        output={
            "scenario": {"key": scenario.scenario_id, "version": scenario.version},
            "agent": {
                "name": config.name,
                "version": config.version,
                "provider": config.provider,
                "model_id": resolve_model_id(config, settings),
            },
            "limits": {
                "max_steps": config.max_steps,
                "max_tool_calls": config.max_tool_calls,
                "timeout_s": config.timeout_s,
            },
        },
    )

    try:
        result = run_scenario(
            scenario,
            config,
            PerCallSopSearcher(session_factory),
            observer=collector,
            sleep=token.wait,
            hooks=RunHooks(
                on_event=collector.on_graph_event,
                should_stop=lambda: token.reason,
                on_pause=token.extend,  # throttle waits push the watchdog back
            ),
            settings=settings,
        )
    except Exception as exc:  # platform failure, not the agent's fault
        if isinstance(exc, ProviderError):  # e.g. the API key was removed after launch
            logger.warning("Run %s could not start its provider: %s", run_id, exc.code)
            error = {"type": type(exc).__name__, **exc.to_dict()}
        else:
            logger.exception("Run %s crashed", run_id)
            error = {
                "code": "platform_error",
                "type": type(exc).__name__,
                "message": str(exc)[:500],
            }
        collector.emit("run_error", error=error)
        if _finish(
            session_factory,
            run_id,
            "running",
            status="errored",
            error_kind="infra",
            error_json=error,
            finished_at=_now(),
        ):
            collector.emit("run_finished", output={"status": "errored", "error_kind": "infra"})
            evaluate_run_safely(session_factory, run_id)
        return

    status, error_kind = _STATUS_FOR_STOP.get(result.stop_reason, ("errored", "agent"))
    if token.reason == "timeout" and result.stop_reason == "cancelled":
        status, error_kind = "timed_out", "agent"
    error_json = None
    if result.errors and status == "errored":
        error_json = _error_json(result)
        collector.emit("run_error", error=error_json)
    finished_at = _now()
    latency_ms = round((finished_at - started_at).total_seconds() * 1000)
    if _finish(
        session_factory,
        run_id,
        "running",
        status=status,
        stop_reason=result.stop_reason,
        error_kind=error_kind,
        error_json=error_json,
        finished_at=finished_at,
        latency_ms=latency_ms,
        steps=result.steps,
        tool_call_count=len(result.tool_calls),
        usage_json=_usage_summary(result),
        throttle_wait_ms=result.paused_ms or None,
        final_outcome_json=result.outcome.model_dump(mode="json") if result.outcome else None,
        actions_json=result.actions,
    ):
        collector.emit(
            "run_finished",
            output={"status": status, "stop_reason": result.stop_reason, "latency_ms": latency_ms},
        )
        evaluate_run_safely(session_factory, run_id)
    else:
        # The watchdog or a cancel finalised the run first; keep that state.
        collector.emit(
            "run_error",
            error={"code": "late_completion_ignored", "stop_reason": result.stop_reason},
        )
