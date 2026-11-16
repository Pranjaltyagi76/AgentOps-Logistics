"""Run and benchmark reports (FR-10), as JSON documents and CSV tables.

Every report carries what is needed to reproduce and audit it: run IDs, scenario keys and
versions, agent name, version and config snapshot, evaluator and diagnoser versions, the score
breakdown, safety-gate failures and the failure items. Demo viewers get the same reports without
the fields that reveal hidden ground truth (expected values, owner-only diagnosis text and
evidence, the advisory judge's rationale).
"""

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import EvaluationResult, Run, Scenario, SuiteRun
from app.services.benchmarks.settle import results_for
from app.services.diagnosis.service import report_for
from app.services.evaluation.service import ensure_diagnosis, latest_evaluation

REPORT_VERSION = "report-v1"
_OWNER_ASSERTION_FIELDS = ("expected", "actual", "detail")
_PUBLIC_JUDGE_FIELDS = (
    "status",
    "advisory",
    "score",
    "uncertainty",
    "judge_model",
    "prompt_version",
    "created_at",
)
RUN_CSV_FIELDS = [
    "run_id",
    "scenario_key",
    "scenario_version",
    "agent_name",
    "agent_version",
    "evaluator_version",
    "verdict",
    "score",
    "assertion_id",
    "component",
    "passed",
    "gate",
    "weighted",
    "summary",
    "cites",
    "expected",
    "actual",
    "detail",
]
COMPONENTS = ["root_cause", "evidence", "tool_correctness", "policy", "response_quality"]
SUITE_CSV_FIELDS = [
    "suite_run_id",
    "suite_name",
    "agent_name",
    "agent_version",
    "run_id",
    "scenario_key",
    "scenario_version",
    "repeat_index",
    "status",
    "evaluator_version",
    "verdict",
    "score",
    *[f"component_{c}" for c in COMPONENTS],
    "gate_failures",
    "main_failure",
    "latency_ms",
    "tokens",
    "is_demo",
]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _evaluation_block(row: EvaluationResult | None, owner: bool) -> dict[str, Any] | None:
    if row is None:
        return None
    assertions = []
    for raw in row.assertions_json:
        item = dict(raw)
        if not owner:
            for key in _OWNER_ASSERTION_FIELDS:
                item.pop(key, None)
        assertions.append(item)
    judge = row.judge_json
    if judge is not None and not owner:
        judge = {k: judge[k] for k in _PUBLIC_JUDGE_FIELDS if k in judge}
    return {
        "evaluator_version": row.evaluator_version,
        "diagnoser_version": row.diagnoser_version,
        "verdict": row.verdict,
        "score": row.score,
        "task_success": row.task_success,
        "pass_threshold": row.pass_threshold,
        "components": row.score_breakdown_json,
        "gate_failures": list(row.policy_violations_json),
        "assertions": assertions,
        "judge": judge,  # advisory only, never part of the score
    }


def run_report(db: Session, run: Run, *, owner: bool) -> dict[str, Any]:
    scenario = db.get(Scenario, run.scenario_id)
    evaluation = latest_evaluation(db, run.id)
    failures: list[dict[str, Any]] = []
    diagnosis_status = None
    if evaluation is not None:
        ensure_diagnosis(db, evaluation)
        stored = report_for(db, evaluation)
        diagnosis_status = stored.status
        for item in stored.items:
            failures.append(
                {
                    "position": item.position,
                    "primary": item.is_primary,
                    "failure_type": item.failure_type,
                    "severity": item.severity,
                    "likely_stage": item.likely_stage,
                    "confidence": item.confidence,
                    "assertion_ids": item.assertion_ids,
                    "trace_refs": item.trace_refs,
                    "summary": item.summary,
                    "debugging_recommendation": item.debugging_recommendation,
                    **(
                        {"diagnosis": item.diagnosis, "evidence": item.evidence_json}
                        if owner
                        else {}
                    ),
                }
            )
    return {
        "report_version": REPORT_VERSION,
        "kind": "run",
        "generated_at": datetime.now(UTC).isoformat(),
        "shows_ground_truth_details": owner,
        "run": {
            "id": str(run.id),
            "suite_run_id": str(run.suite_run_id) if run.suite_run_id else None,
            "repeat_index": run.repeat_index,
            "status": run.status,
            "stop_reason": run.stop_reason,
            "error_kind": run.error_kind,
            "error": run.error_json,
            "is_demo": run.is_demo,
            "triggered_by_role": run.triggered_by_role,
            "created_at": _iso(run.created_at),
            "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at),
            "latency_ms": run.latency_ms,
            "throttle_wait_ms": run.throttle_wait_ms,
            "steps": run.steps,
            "tool_call_count": run.tool_call_count,
            "usage": run.usage_json,
            "outcome": run.final_outcome_json,
        },
        "scenario": {
            "key": run.scenario_key,
            "version": run.scenario_version,
            "title": scenario.title if scenario else None,
            "category": scenario.category if scenario else None,
        },
        "agent": {
            "name": run.agent_name,
            "version": run.agent_version,
            "provider": run.provider,
            "model": (run.versions_json or {}).get("model"),
            "config_snapshot": run.config_snapshot_json,
        },
        "versions": run.versions_json,
        "evaluation": _evaluation_block(evaluation, owner),
        "failures": {"status": diagnosis_status, "items": failures},
    }


def run_report_csv(report: dict[str, Any]) -> str:
    """One row per evaluator check."""
    evaluation = report["evaluation"] or {}
    base = {
        "run_id": report["run"]["id"],
        "scenario_key": report["scenario"]["key"],
        "scenario_version": report["scenario"]["version"],
        "agent_name": report["agent"]["name"],
        "agent_version": report["agent"]["version"],
        "evaluator_version": evaluation.get("evaluator_version"),
        "verdict": evaluation.get("verdict"),
        "score": evaluation.get("score"),
    }
    rows = [
        {
            **base,
            "assertion_id": a["id"],
            "component": a["component"],
            "passed": a["passed"],
            "gate": a["gate"],
            "weighted": a["weighted"],
            "summary": a["summary"],
            "cites": " ".join(a.get("cites", [])),
            "expected": _cell(a.get("expected")),
            "actual": _cell(a.get("actual")),
            "detail": a.get("detail", ""),
        }
        for a in evaluation.get("assertions", [])
    ]
    return _csv(RUN_CSV_FIELDS, rows or [base])


def suite_report(db: Session, suite_run: SuiteRun, *, owner: bool) -> dict[str, Any]:
    results = results_for(db, suite_run.id)
    failure_counts: dict[str, int] = {}
    runs = []
    for r in results:
        run = db.get(Run, r.run_id)
        report = run_report(db, run, owner=owner) if run is not None else None
        items = report["failures"]["items"] if report else []
        for item in items:
            failure_counts[item["failure_type"]] = failure_counts.get(item["failure_type"], 0) + 1
        runs.append(
            {
                "run_id": r.run_id,
                "scenario_key": r.scenario_key,
                "scenario_version": r.scenario_version,
                "repeat_index": r.repeat_index,
                "status": r.status,
                "evaluator_version": r.evaluator_version,
                "verdict": r.verdict,
                "score": r.score,
                "components": r.components,
                "gate_failures": list(r.gate_failures),
                "main_failure": r.main_failure,
                "failures": items,
                "latency_ms": r.latency_ms,
                "tokens": r.tokens,
                "is_demo": run.is_demo if run else None,
            }
        )
    summary = suite_run.summary_json or {}
    return {
        "report_version": REPORT_VERSION,
        "kind": "benchmark",
        "generated_at": datetime.now(UTC).isoformat(),
        "shows_ground_truth_details": owner,
        "suite_run": {
            "id": str(suite_run.id),
            "suite_id": str(suite_run.suite_id),
            "suite_name": suite_run.suite_name,
            "status": suite_run.status,
            "repeats": suite_run.repeats,
            "total_runs": suite_run.total_runs,
            "is_demo": suite_run.is_demo,
            "created_at": _iso(suite_run.created_at),
            "started_at": _iso(suite_run.started_at),
            "finished_at": _iso(suite_run.finished_at),
            "scenarios": suite_run.scenarios_json,
        },
        "agent": {
            "name": suite_run.agent_name,
            "version": suite_run.agent_version,
            "provider": suite_run.provider,
        },
        "evaluator_versions": summary.get("evaluator_versions", []),
        "metrics": summary.get("metrics"),
        "flaky": summary.get("flaky", []),
        "failure_counts": dict(sorted(failure_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "runs": runs,
    }


def suite_report_csv(report: dict[str, Any]) -> str:
    """One row per run."""
    suite = report["suite_run"]
    rows = [
        {
            "suite_run_id": suite["id"],
            "suite_name": suite["suite_name"],
            "agent_name": report["agent"]["name"],
            "agent_version": report["agent"]["version"],
            "run_id": r["run_id"],
            "scenario_key": r["scenario_key"],
            "scenario_version": r["scenario_version"],
            "repeat_index": r["repeat_index"],
            "status": r["status"],
            "evaluator_version": r["evaluator_version"],
            "verdict": r["verdict"],
            "score": r["score"],
            **{f"component_{c}": r["components"].get(c) for c in COMPONENTS},
            "gate_failures": " ".join(r["gate_failures"]),
            "main_failure": r["main_failure"],
            "latency_ms": r["latency_ms"],
            "tokens": r["tokens"],
            "is_demo": r["is_demo"],
        }
        for r in report["runs"]
    ]
    return _csv(SUITE_CSV_FIELDS, rows)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _csv(fields: list[str], rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows({k: ("" if v is None else v) for k, v in row.items()} for row in rows)
    return buffer.getvalue()
