"""Dashboard KPIs and report exports over the golden MVP suites (database)."""

import csv
import io
import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.db.models import EvaluationResult, Run, SuiteRun
from app.services.benchmarks.service import SuiteService
from app.services.reports.service import RUN_CSV_FIELDS, SUITE_CSV_FIELDS
from tests.helpers import H
from tests.test_suites import completed_suite_run

pytestmark = pytest.mark.db

V2_MAIN_FINDINGS = {
    "unsupported_claim": 3,
    "wrong_root_cause": 2,
    "missed_escalation": 2,
    "forbidden_action": 1,
    "missing_evidence": 1,
}


@pytest.fixture
def suites(
    api: TestClient, owner_headers: H, ids: dict[str, uuid.UUID], suite_id: uuid.UUID
) -> dict[str, dict[str, Any]]:
    return {
        "v1": completed_suite_run(api, owner_headers, suite_id, ids["rule-based-v1"]),
        "v2": completed_suite_run(api, owner_headers, suite_id, ids["rule-based-v2-flawed"]),
    }


def kpis(api: TestClient, headers: H, **params: Any) -> dict[str, Any]:
    response = api.get("/api/v1/dashboard/summary", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def values(body: dict[str, Any]) -> dict[str, Any]:
    return {k["key"]: k["value"] for k in body["kpis"]}


# --- dashboard ---------------------------------------------------------------------------------


def test_kpis_match_hand_computed_values(
    api: TestClient, viewer_headers: H, suites: dict, db_session: Session
) -> None:
    body = kpis(api, viewer_headers)
    v = values(body)
    assert v["total_scenarios"] == 10
    assert (v["total_runs"], v["scored_runs"], v["platform_errors"]) == (20, 20, 0)
    assert v["pass_rate"] == 0.6  # v1 10 + v2 2 of 20
    assert v["task_success_rate"] == 0.6
    assert v["root_cause_accuracy"] == 0.85  # v1 10 + v2 7
    assert v["policy_violations"] == 6
    assert v["escalation_accuracy"] == 0.9  # v2 missed 2 required escalations
    assert v["estimated_cost_usd"] is None
    assert v["mean_latency_ms"] is not None

    # Independent check of the component average straight from the stored evaluations.
    rows = db_session.scalars(select(EvaluationResult)).all()
    tool = [
        c["score"] for r in rows for c in r.score_breakdown_json if c["name"] == "tool_correctness"
    ]
    assert v["tool_correctness"] == round(sum(tool) / len(tool), 4)

    mains = {f["failure_type"]: f["main_findings"] for f in body["failure_types"]}
    assert {k: c for k, c in mains.items() if c} == V2_MAIN_FINDINGS
    versions = {a["agent_name"]: a for a in body["agent_versions"]}
    assert versions["rule-based-v1"]["pass_rate"] == 1.0
    assert versions["rule-based-v2-flawed"]["pass_rate"] == 0.2
    assert versions["rule-based-v2-flawed"]["policy_violation_rate"] == 0.6
    assert len(body["recent_runs"]) == 10 and len(body["recent_suite_runs"]) == 2


def test_every_kpi_is_its_own_sql_query(
    api: TestClient, viewer_headers: H, suites: dict, db_session: Session
) -> None:
    body = kpis(api, viewer_headers)
    for kpi in body["kpis"]:
        assert kpi["definition"] and kpi["sql"].lstrip().upper().startswith("SELECT")
        raw = db_session.execute(text(kpi["sql"]), {"include_demo": True}).scalar()
        if kpi["value"] is None:
            assert raw is None, kpi["key"]
        else:
            assert float(raw) == pytest.approx(kpi["value"], abs=1e-3), kpi["key"]


def test_demo_data_and_platform_errors_are_excluded_from_rates(
    api: TestClient, viewer_headers: H, suites: dict, db_session: Session
) -> None:
    v2_runs = [uuid.UUID(r["run_id"]) for r in suites["v2"]["results"]]
    db_session.execute(update(Run).where(Run.id.in_(v2_runs)).values(is_demo=True))
    without = kpis(api, viewer_headers, include_demo=False)
    assert without["demo_runs"] == 10 and without["include_demo"] is False
    v = values(without)
    assert (v["total_runs"], v["pass_rate"], v["policy_violations"]) == (10, 1.0, 0)
    assert all(not r["is_demo"] for r in without["recent_runs"])
    assert {a["agent_name"] for a in without["agent_versions"]} == {"rule-based-v1"}

    one = uuid.UUID(suites["v1"]["results"][0]["run_id"])
    db_session.execute(update(Run).where(Run.id == one).values(verdict="ERROR"))
    v = values(kpis(api, viewer_headers, include_demo=False))
    assert (v["scored_runs"], v["platform_errors"], v["pass_rate"]) == (9, 1, 1.0)


def test_an_empty_database_reports_unknown_not_zero(api: TestClient, viewer_headers: H) -> None:
    v = values(kpis(api, viewer_headers))
    assert v["total_runs"] == 0 and v["scored_runs"] == 0
    for key in (
        "pass_rate",
        "root_cause_accuracy",
        "tool_correctness",
        "escalation_accuracy",
        "mean_latency_ms",
        "estimated_cost_usd",
    ):
        assert v[key] is None, key


# --- reports -----------------------------------------------------------------------------------


def report(api: TestClient, headers: H, path: str, fmt: str = "json"):  # type: ignore[no-untyped-def]
    response = api.get(f"/api/v1/reports/{path}", params={"format": fmt}, headers=headers)
    assert response.status_code == 200, response.text
    return response


def test_run_report_has_everything_needed_to_reproduce_it(
    api: TestClient, owner_headers: H, viewer_headers: H, suites: dict
) -> None:
    refund = next(
        r for r in suites["v2"]["results"] if r["scenario_key"] == "policy_refund_demand_001"
    )
    owner = report(api, owner_headers, f"runs/{refund['run_id']}").json()
    assert owner["report_version"] == "report-v1" and owner["kind"] == "run"
    assert owner["run"]["id"] == refund["run_id"]
    assert owner["scenario"] == {
        "key": "policy_refund_demand_001",
        "version": 1,
        "title": owner["scenario"]["title"],
        "category": owner["scenario"]["category"],
    }
    assert owner["agent"]["name"] == "rule-based-v2-flawed" and owner["agent"]["version"] == 1
    assert owner["agent"]["config_snapshot"]["name"] == "rule-based-v2-flawed"
    evaluation = owner["evaluation"]
    assert evaluation["evaluator_version"] == "eval-v2"
    assert evaluation["diagnoser_version"] == "diag-v1"
    assert {c["name"] for c in evaluation["components"]} >= {"root_cause", "policy"}
    assert "no_forbidden_action" in evaluation["gate_failures"]
    assert any(
        i["primary"] and i["failure_type"] == "missed_escalation"
        for i in owner["failures"]["items"]
    )
    assert any("expected" in a for a in evaluation["assertions"])

    viewer = report(api, viewer_headers, f"runs/{refund['run_id']}")
    body = viewer.json()
    assert body["shows_ground_truth_details"] is False
    assert all("expected" not in a for a in body["evaluation"]["assertions"])
    assert all("diagnosis" not in i for i in body["failures"]["items"])


def test_run_report_csv_has_one_row_per_check(
    api: TestClient, owner_headers: H, suites: dict
) -> None:
    run_id = suites["v1"]["results"][0]["run_id"]
    response = report(api, owner_headers, f"runs/{run_id}", "csv")
    assert response.headers["content-type"].startswith("text/csv")
    assert f"run-{run_id}.csv" in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert list(rows[0]) == RUN_CSV_FIELDS
    as_json = report(api, owner_headers, f"runs/{run_id}").json()
    assert len(rows) == len(as_json["evaluation"]["assertions"])
    assert {r["run_id"] for r in rows} == {run_id}
    assert {r["evaluator_version"] for r in rows} == {"eval-v2"}


def test_benchmark_report_json_and_csv(api: TestClient, viewer_headers: H, suites: dict) -> None:
    suite_run_id = suites["v2"]["id"]
    body = report(api, viewer_headers, f"suite-runs/{suite_run_id}").json()
    assert body["kind"] == "benchmark" and body["suite_run"]["id"] == suite_run_id
    assert body["agent"] == {"name": "rule-based-v2-flawed", "version": 1, "provider": "rule_based"}
    assert body["evaluator_versions"] == ["eval-v2"]
    assert body["metrics"]["task_success_rate"] == 0.2
    assert len(body["runs"]) == 10
    assert {r["scenario_version"] for r in body["runs"]} == {1}
    assert body["failure_counts"]["missed_escalation"] == 2
    assert all("diagnosis" not in i for r in body["runs"] for i in r["failures"])
    json.dumps(body)  # serialisable as-is

    response = report(api, viewer_headers, f"suite-runs/{suite_run_id}", "csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert list(rows[0]) == SUITE_CSV_FIELDS and len(rows) == 10
    refund = next(r for r in rows if r["scenario_key"] == "policy_refund_demand_001")
    assert refund["verdict"] == "FAILED_POLICY" and refund["main_failure"] == "missed_escalation"
    assert "no_forbidden_action" in refund["gate_failures"]


def test_unknown_report_targets(api: TestClient, viewer_headers: H) -> None:
    for path in (f"runs/{uuid.uuid4()}", f"suite-runs/{uuid.uuid4()}"):
        assert api.get(f"/api/v1/reports/{path}", headers=viewer_headers).status_code == 404
    bad = api.get(
        f"/api/v1/reports/runs/{uuid.uuid4()}", params={"format": "pdf"}, headers=viewer_headers
    )
    assert bad.status_code == 422


def test_demo_launches_mark_every_run(
    make_api: Any, ids: dict[str, uuid.UUID], suite_id: uuid.UUID, db_session: Session
) -> None:
    from app.api.deps import Principal

    api = make_api()
    state = api.app.state  # type: ignore[attr-defined]
    from app.services.execution.service import RunService

    runs = RunService(
        db_session, state.settings, state.executor, state.session_factory, state.run_limiter
    )
    seed = Principal(subject="demo-seed", role="owner", email=None)
    suite_run = SuiteService(db_session, runs).launch(
        suite_id, ids["rule-based-v1"], 1, seed, is_demo=True
    )
    db_session.expire_all()
    row = db_session.get(SuiteRun, suite_run.id)
    assert row is not None and row.is_demo and row.status == "completed"
    children = db_session.scalars(select(Run).where(Run.suite_run_id == suite_run.id)).all()
    assert len(children) == 10 and all(r.is_demo for r in children)
