"""Suite-run results and finalising (Phase 8).

Kept apart from the suite service so the run worker can call it without an import cycle.

- `results_for` turns a suite run's persisted runs, evaluations, trace tool events and
  failure reports into `RunResult`s for the metrics and the comparison.
- `settle_suite_run` marks a suite run running once a child starts, and completed (or
  cancelled) with its metrics once every child is final. Status changes are compare-and-set,
  so concurrent finishing runs settle it exactly once.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import EvaluationResult, FailureReport, Run, SuiteRun, TraceEvent
from app.domain.metrics import RunResult, suite_metrics
from app.domain.scoring import TOOL_EVENTS
from app.services.evaluation.service import latest_evaluation, records_from_events
from app.services.execution.collector import SessionFactory

logger = logging.getLogger(__name__)

ACTIVE = ("queued", "running")


def _list(value: object) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def result_for(
    run: Run,
    evaluation: EvaluationResult | None,
    tool_events: list[TraceEvent],
    main_failure: str | None,
) -> RunResult:
    records = records_from_events(tool_events)
    valid = [r for r in records if r.is_valid_call]
    usage = run.usage_json or {}
    llm_free = run.provider == "rule_based"
    fields: dict = {"verdict": None}  # not scored (cancelled)
    if evaluation is not None:
        assertions = {a["id"]: a for a in evaluation.assertions_json}
        evidence = assertions.get("required_evidence_cited") or {}
        expected, cited = _list(evidence.get("expected")), _list(evidence.get("actual"))
        escalation = assertions.get("escalation_expected") or {}
        fields = {
            "verdict": evaluation.verdict,
            "score": evaluation.score,
            "evaluator_version": evaluation.evaluator_version,
            "components": {
                c["name"]: (c["score"] if c.get("enabled") else None)
                for c in evaluation.score_breakdown_json
            },
            "gate_failures": tuple(evaluation.policy_violations_json),
            "root_cause_ok": (assertions.get("root_cause_match") or {}).get("passed"),
            "evidence_required": len(expected),
            "evidence_found": len([e for e in expected if e in cited]),
            "escalation_expected": escalation.get("expected"),
            "escalated": escalation.get("actual"),
        }
    return RunResult(
        run_id=str(run.id),
        scenario_key=run.scenario_key,
        scenario_version=run.scenario_version,
        repeat_index=run.repeat_index,
        status=run.status,
        calls_attempted=len(records),
        calls_valid=len(valid),
        calls_executed=len([r for r in valid if r.event_type != "policy_denied"]),
        calls_succeeded=len([r for r in records if r.event_type == "tool_result"]),
        latency_ms=run.latency_ms,
        steps=run.steps,
        input_tokens=0 if llm_free else usage.get("input_tokens"),
        output_tokens=0 if llm_free else usage.get("output_tokens"),
        main_failure=main_failure,
        **fields,
    )


def results_for(db: Session, suite_run_id: uuid.UUID) -> list[RunResult]:
    runs = list(
        db.scalars(
            select(Run)
            .where(Run.suite_run_id == suite_run_id)
            .order_by(Run.scenario_key, Run.repeat_index)
        )
    )
    if not runs:
        return []
    ids = [r.id for r in runs]
    events: dict[uuid.UUID, list[TraceEvent]] = {i: [] for i in ids}
    for event in db.scalars(
        select(TraceEvent)
        .where(TraceEvent.run_id.in_(ids), TraceEvent.event_type.in_(TOOL_EVENTS))
        .order_by(TraceEvent.run_id, TraceEvent.seq)
    ):
        events[event.run_id].append(event)
    evaluations = {r.id: latest_evaluation(db, r.id) for r in runs}
    evaluation_ids = [e.id for e in evaluations.values() if e is not None]
    primary = (
        {
            row.evaluation_id: row.failure_type
            for row in db.scalars(
                select(FailureReport).where(
                    FailureReport.evaluation_id.in_(evaluation_ids), FailureReport.is_primary
                )
            )
        }
        if evaluation_ids
        else {}
    )
    return [
        result_for(
            run,
            evaluations[run.id],
            events[run.id],
            primary.get(evaluations[run.id].id) if evaluations[run.id] is not None else None,  # type: ignore[union-attr]
        )
        for run in runs
    ]


def settle_suite_run(session_factory: SessionFactory, suite_run_id: uuid.UUID) -> None:
    with session_factory() as db:
        suite_run = db.get(SuiteRun, suite_run_id)
        if suite_run is None or suite_run.status not in ACTIVE:
            return
        statuses = list(db.scalars(select(Run.status).where(Run.suite_run_id == suite_run_id)))
        now = datetime.now(UTC)
        if any(s in ACTIVE for s in statuses):
            if any(s != "queued" for s in statuses):
                db.execute(
                    update(SuiteRun)
                    .where(SuiteRun.id == suite_run_id, SuiteRun.status == "queued")
                    .values(status="running", started_at=now)
                )
                db.commit()
            return
        results = results_for(db, suite_run_id)
        versions = sorted({r.evaluator_version for r in results if r.evaluator_version})
        summary = {
            "metrics": suite_metrics(results).to_json(),
            "evaluator_versions": versions,
            "flaky": sorted(
                {
                    r.scenario_key
                    for r in results
                    if len(
                        {
                            x.verdict
                            for x in results
                            if x.scenario_key == r.scenario_key and x.verdict is not None
                        }
                    )
                    > 1
                }
            ),
        }
        db.execute(
            update(SuiteRun)
            .where(SuiteRun.id == suite_run_id, SuiteRun.status.in_(ACTIVE))
            .values(
                status="cancelled" if suite_run.cancel_requested else "completed",
                started_at=suite_run.started_at or now,
                finished_at=now,
                summary_json=summary,
                evaluator_version=versions[0] if len(versions) == 1 else None,
            )
        )
        db.commit()


def settle_for_run(session_factory: SessionFactory, run_id: uuid.UUID) -> None:
    """Called whenever a run reaches a final state; never raises into the caller."""
    try:
        with session_factory() as db:
            suite_run_id = db.scalar(select(Run.suite_run_id).where(Run.id == run_id))
        if suite_run_id is not None:
            settle_suite_run(session_factory, suite_run_id)
    except Exception:
        logger.exception("Settling the suite run of run %s failed", run_id)


def mark_suite_started(db: Session, suite_run_id: uuid.UUID) -> None:
    db.execute(
        update(SuiteRun)
        .where(SuiteRun.id == suite_run_id, SuiteRun.status == "queued")
        .values(status="running", started_at=datetime.now(UTC))
    )
