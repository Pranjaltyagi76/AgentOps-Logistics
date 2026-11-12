"""Scores finished runs from their saved trace and stores the result.

Each evaluation is diagnosed in the same transaction (diag-v1, Phase 7).

Called by the run worker right after a run finishes, by the sweeper for orphaned runs, by the
re-evaluate endpoint, and by scripts/evaluate_runs.py. Cancelled runs are not scored: the
user stopped them, so they say nothing about the agent.
"""

import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import EvaluationResult, Run, Scenario, TraceEvent
from app.domain.diagnosis_rules import diagnose
from app.domain.scoring import (
    EVALUATOR_VERSION,
    Assertion,
    Evaluation,
    RunFacts,
    TraceRecord,
    evaluate,
)
from app.schemas.scenario import ScenarioSpec
from app.services.agent_graph.graph import AgentRunResult
from app.services.diagnosis.service import store_diagnosis
from app.services.execution.collector import SessionFactory

logger = logging.getLogger(__name__)

NOT_SCORED = frozenset({"queued", "running", "cancelled"})


def records_from_events(events: list[TraceEvent]) -> tuple[TraceRecord, ...]:
    return tuple(
        TraceRecord(
            seq=e.seq,
            event_type=e.event_type,
            tool=e.tool_name,
            input=e.input_json,
            output=e.output_json,
            error=e.error_json,
            evidence_ids=tuple(e.evidence_ids or ()),
        )
        for e in events
    )


def facts_from_result(result: AgentRunResult, status: str = "completed") -> RunFacts:
    """Facts for an in-memory run (used by scripts/run_agent.py, which saves no trace)."""
    records: list[TraceRecord] = []
    for call in result.tool_calls:
        body = call.outcome.model_dump(mode="json")
        if call.ok:
            event_type, error = "tool_result", None
        else:
            event_type = "policy_denied" if body["code"] == "policy_denied" else "tool_error"
            error = {k: body[k] for k in ("code", "message", "retryable", "details")}
        records.append(
            TraceRecord(
                seq=len(records) + 1,
                event_type=event_type,
                tool=call.tool,
                input={"arguments": call.arguments},
                output=body.get("data"),
                error=error,
                evidence_ids=tuple(body.get("evidence_ids", [])),
            )
        )
    outcome = result.outcome.model_dump(mode="json") if result.outcome else None
    if outcome is not None:
        records.append(
            TraceRecord(
                seq=len(records) + 1,
                event_type="outcome_submitted",
                output=outcome,
                evidence_ids=tuple(outcome["evidence_ids"]),
            )
        )
    return RunFacts(status, result.stop_reason, None, tuple(records), outcome)


def load_run_facts(db: Session, run: Run) -> tuple[ScenarioSpec, RunFacts]:
    """The scenario (with ground truth) and the run's facts rebuilt from its saved trace."""
    scenario = db.get(Scenario, run.scenario_id)
    assert scenario is not None
    spec = ScenarioSpec.model_validate(scenario.scenario_json)
    events = list(
        db.scalars(select(TraceEvent).where(TraceEvent.run_id == run.id).order_by(TraceEvent.seq))
    )
    facts = RunFacts(
        status=run.status,
        stop_reason=run.stop_reason,
        error_kind=run.error_kind,
        records=records_from_events(events),
        outcome=run.final_outcome_json,
    )
    return spec, facts


def evaluate_loaded(db: Session, run: Run) -> Evaluation | None:
    if run.status in NOT_SCORED:
        return None
    spec, facts = load_run_facts(db, run)
    return evaluate(spec, facts)


def evaluate_run(db: Session, run_id: uuid.UUID) -> EvaluationResult | None:
    """Scores one run and stores the result (replacing a result of the same version)."""
    run = db.get(Run, run_id)
    if run is None or run.status in NOT_SCORED:
        return None
    spec, facts = load_run_facts(db, run)
    evaluation = evaluate(spec, facts)
    payload = evaluation.to_json()
    previous = db.scalar(
        select(EvaluationResult).where(
            EvaluationResult.run_id == run_id,
            EvaluationResult.evaluator_version == evaluation.version,
        )
    )
    judge_json = previous.judge_json if previous is not None else None  # judged the same reply
    db.execute(
        delete(EvaluationResult).where(
            EvaluationResult.run_id == run_id,
            EvaluationResult.evaluator_version == evaluation.version,
        )
    )
    row = EvaluationResult(
        run_id=run_id,
        evaluator_version=evaluation.version,
        verdict=evaluation.verdict,
        score=evaluation.score,
        task_success=evaluation.task_success,
        pass_threshold=evaluation.threshold,
        score_breakdown_json=payload["components"],
        assertions_json=payload["assertions"],
        policy_violations_json=evaluation.gate_failures,
        judge_json=judge_json,
    )
    db.add(row)
    db.flush()
    # Diagnosis is part of scoring: same facts, same transaction (Phase 7).
    store_diagnosis(db, row, diagnose(spec, evaluation.verdict, evaluation.assertions, facts))
    run.verdict = evaluation.verdict
    run.score = evaluation.score
    run.policy_failed = bool(evaluation.gate_failures)
    run.versions_json = {**(run.versions_json or {}), "evaluator": evaluation.version}
    db.commit()
    return row


def ensure_diagnosis(db: Session, evaluation: EvaluationResult) -> None:
    """Diagnoses an evaluation stored before Phase 7 (deterministic, so safe to do on read)."""
    if evaluation.diagnoser_version is not None:
        return
    run = db.get(Run, evaluation.run_id)
    assert run is not None
    spec, facts = load_run_facts(db, run)
    assertions = [Assertion(**raw) for raw in evaluation.assertions_json]
    store_diagnosis(db, evaluation, diagnose(spec, evaluation.verdict, assertions, facts))
    db.commit()


def evaluate_run_safely(session_factory: SessionFactory, run_id: uuid.UUID) -> None:
    """Never lets an evaluator bug change a run's execution status."""
    try:
        with session_factory() as db:
            evaluate_run(db, run_id)
    except Exception:
        logger.exception("Evaluation of run %s failed", run_id)


def latest_evaluation(db: Session, run_id: uuid.UUID) -> EvaluationResult | None:
    return db.scalar(
        select(EvaluationResult)
        .where(EvaluationResult.run_id == run_id)
        .order_by(
            (EvaluationResult.evaluator_version == EVALUATOR_VERSION).desc(),
            EvaluationResult.created_at.desc(),
        )
        .limit(1)
    )
