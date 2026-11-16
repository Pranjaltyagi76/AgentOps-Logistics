"""Dashboard KPIs (FR-09). Every number is one SQL query over persisted rows, kept here as SQL
text so it can be shown next to the value and audited (Phase 9 acceptance).

Conventions:
- "In scope" runs: all runs, or only non-demo runs when demo data is excluded.
- "Scored" runs: in scope, with a verdict other than ERROR. Platform errors and unscored
  (cancelled, unfinished) runs are excluded from every rate.
- A run's current evaluation is the stored result of the evaluator version recorded on the run
  (`runs.versions_json->>'evaluator'`); its current failure report is the one produced by that
  evaluation's diagnoser version.
- A rate with no runs to divide by is None ("unknown"), never 0. Cost is always unknown: there
  is no verified price list (benchmark.md §9).
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

DASHBOARD_VERSION = "dashboard-v1"

_SCOPE = "(:include_demo OR NOT r.is_demo)"
_CURRENT = (
    "JOIN evaluation_results e ON e.run_id = r.id "
    "AND e.evaluator_version = r.versions_json->>'evaluator'"
)
_SCORED = f"{_SCOPE} AND r.verdict IS NOT NULL AND r.verdict <> 'ERROR'"


def _assertion_passed(assertion_id: str) -> str:
    return (
        "EXISTS (SELECT 1 FROM jsonb_array_elements(e.assertions_json) a "
        f"WHERE a->>'id' = '{assertion_id}' AND (a->>'passed')::boolean)"
    )


@dataclass(frozen=True)
class Kpi:
    key: str
    label: str
    unit: str  # count | rate | score | ms | usd
    definition: str
    sql: str


KPIS: list[Kpi] = [
    Kpi(
        "total_scenarios",
        "Scenarios",
        "count",
        "Distinct active scenario keys",
        "SELECT count(DISTINCT scenario_key) AS value FROM scenarios WHERE status = 'active'",
    ),
    Kpi(
        "total_runs",
        "Runs",
        "count",
        "Runs in scope (any status)",
        f"SELECT count(*) AS value FROM runs r WHERE {_SCOPE}",
    ),
    Kpi(
        "scored_runs",
        "Scored runs",
        "count",
        "Runs in scope with a verdict other than ERROR",
        f"SELECT count(*) AS value FROM runs r WHERE {_SCORED}",
    ),
    Kpi(
        "platform_errors",
        "Platform errors",
        "count",
        "Runs in scope with verdict ERROR (not counted against agents)",
        f"SELECT count(*) AS value FROM runs r WHERE {_SCOPE} AND r.verdict = 'ERROR'",
    ),
    Kpi(
        "pass_rate",
        "Pass rate",
        "rate",
        "PASS runs / scored runs",
        "SELECT avg(CASE WHEN r.verdict = 'PASS' THEN 1.0 ELSE 0.0 END) AS value "
        f"FROM runs r WHERE {_SCORED}",
    ),
    Kpi(
        "task_success_rate",
        "Task success",
        "rate",
        "Scored runs whose current evaluation has task_success / scored runs",
        "SELECT avg(CASE WHEN e.task_success THEN 1.0 ELSE 0.0 END) AS value "
        f"FROM runs r {_CURRENT} WHERE {_SCORED}",
    ),
    Kpi(
        "root_cause_accuracy",
        "Root-cause accuracy",
        "rate",
        "Scored runs whose root_cause_match check passed / scored runs",
        f"SELECT avg(CASE WHEN {_assertion_passed('root_cause_match')} THEN 1.0 ELSE 0.0 END) "
        f"AS value FROM runs r {_CURRENT} WHERE {_SCORED}",
    ),
    Kpi(
        "tool_correctness",
        "Tool correctness",
        "score",
        "Mean tool_correctness component score (0-1) over scored runs",
        "SELECT avg((c->>'score')::float) AS value FROM runs r "
        f"{_CURRENT} CROSS JOIN LATERAL jsonb_array_elements(e.score_breakdown_json) c "
        f"WHERE {_SCORED} AND c->>'name' = 'tool_correctness' AND (c->>'enabled')::boolean",
    ),
    Kpi(
        "policy_violations",
        "Policy violations",
        "count",
        "Scored runs that failed at least one safety gate",
        f"SELECT count(*) AS value FROM runs r WHERE {_SCORED} AND r.policy_failed",
    ),
    Kpi(
        "escalation_accuracy",
        "Escalation accuracy",
        "rate",
        "Scored runs whose escalation_expected check passed / scored runs that have the check",
        "SELECT avg(CASE WHEN (a->>'passed')::boolean THEN 1.0 ELSE 0.0 END) AS value "
        f"FROM runs r {_CURRENT} CROSS JOIN LATERAL jsonb_array_elements(e.assertions_json) a "
        f"WHERE {_SCORED} AND a->>'id' = 'escalation_expected' AND a->>'passed' IS NOT NULL",
    ),
    Kpi(
        "mean_latency_ms",
        "Average latency",
        "ms",
        "Mean wall-clock latency of completed runs in scope",
        "SELECT avg(r.latency_ms)::float AS value FROM runs r "
        f"WHERE {_SCOPE} AND r.status = 'completed' AND r.latency_ms IS NOT NULL",
    ),
    Kpi(
        "estimated_cost_usd",
        "Estimated cost",
        "usd",
        "Unknown: no verified, dated price list (the free tier costs $0)",
        "SELECT NULL::float AS value",
    ),
]

FAILURE_TYPES_SQL = (
    "SELECT f.failure_type, count(*) AS items, "
    "count(*) FILTER (WHERE f.is_primary) AS main_findings, count(DISTINCT r.id) AS runs "
    f"FROM runs r {_CURRENT} JOIN failure_reports f ON f.evaluation_id = e.id "
    "AND f.diagnoser_version = e.diagnoser_version "
    f"WHERE {_SCORED} GROUP BY f.failure_type ORDER BY items DESC, f.failure_type"
)

AGENT_VERSIONS_SQL = (
    "SELECT r.agent_name, r.agent_version, r.provider, count(*) AS runs, "
    "avg(CASE WHEN r.verdict = 'PASS' THEN 1.0 ELSE 0.0 END) AS pass_rate, "
    "avg(r.score) AS mean_score, "
    "avg(CASE WHEN r.policy_failed THEN 1.0 ELSE 0.0 END) AS policy_violation_rate, "
    "avg(r.latency_ms)::float AS mean_latency_ms "
    f"FROM runs r WHERE {_SCORED} "
    "GROUP BY r.agent_name, r.agent_version, r.provider "
    "ORDER BY r.agent_name, r.agent_version"
)

RECENT_RUNS_SQL = (
    "SELECT r.id, r.scenario_key, r.scenario_version, r.agent_name, r.agent_version, r.provider, "
    "r.status, r.verdict, r.score, r.is_demo, r.created_at FROM runs r "
    f"WHERE {_SCOPE} ORDER BY r.created_at DESC LIMIT 10"
)

RECENT_SUITE_RUNS_SQL = (
    "SELECT s.id, s.suite_name, s.agent_name, s.agent_version, s.status, s.total_runs, "
    "s.is_demo, s.created_at, (s.summary_json->'metrics'->>'task_success_rate')::float "
    "AS task_success_rate FROM suite_runs s "
    "WHERE (:include_demo OR NOT s.is_demo) ORDER BY s.created_at DESC LIMIT 5"
)

DEMO_COUNT_SQL = "SELECT count(*) FROM runs WHERE is_demo"


def _value(raw: Any, unit: str) -> float | int | None:
    if raw is None:
        return None
    if unit == "count":
        return int(raw)
    return round(float(raw), 4 if unit in ("rate", "score") else 1)


def _rows(db: Session, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row._mapping) for row in db.execute(text(sql), params)]


def summary(db: Session, *, include_demo: bool = True) -> dict[str, Any]:
    params = {"include_demo": include_demo}
    kpis = []
    for kpi in KPIS:
        raw = db.execute(text(kpi.sql), params).scalar()
        kpis.append(
            {
                "key": kpi.key,
                "label": kpi.label,
                "unit": kpi.unit,
                "value": _value(raw, kpi.unit),
                "definition": kpi.definition,
                "sql": kpi.sql,
            }
        )
    versions = []
    for row in _rows(db, AGENT_VERSIONS_SQL, params):
        versions.append(
            {
                **row,
                "pass_rate": _value(row["pass_rate"], "rate"),
                "mean_score": _value(row["mean_score"], "ms"),
                "policy_violation_rate": _value(row["policy_violation_rate"], "rate"),
                "mean_latency_ms": _value(row["mean_latency_ms"], "ms"),
            }
        )
    return {
        "version": DASHBOARD_VERSION,
        "include_demo": include_demo,
        "demo_runs": int(db.execute(text(DEMO_COUNT_SQL)).scalar() or 0),
        "kpis": kpis,
        "failure_types": _rows(db, FAILURE_TYPES_SQL, params),
        "agent_versions": versions,
        "recent_runs": _rows(db, RECENT_RUNS_SQL, params),
        "recent_suite_runs": _rows(db, RECENT_SUITE_RUNS_SQL, params),
        "queries": {
            "failure_types": FAILURE_TYPES_SQL,
            "agent_versions": AGENT_VERSIONS_SQL,
        },
    }
