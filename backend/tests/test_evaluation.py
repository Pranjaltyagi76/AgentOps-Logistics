"""End-to-end scoring through the runs API (database)."""

import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.db.models import EvaluationResult, Run
from app.services.evaluation.service import evaluate_run
from app.services.execution.service import sweep_orphaned_runs
from tests.conftest import ManualExecutor
from tests.helpers import RUNS, H, launch

pytestmark = pytest.mark.db

SCENARIOS = [
    "ambiguity_insufficient_evidence_001",
    "carrier_api_timeout_001",
    "data_invalid_timestamp_001",
    "delay_hub_congestion_001",
    "delay_weather_hold_001",
    "delivery_customer_unavailable_001",
    "eta_unsupported_request_001",
    "policy_refund_demand_001",
    "sla_breach_escalation_001",
    "tracking_missing_scan_001",
]

# The flawed agent's designed failures (see rule_based.py and benchmark.md §10).
V2_VERDICTS = {
    "ambiguity_insufficient_evidence_001": "FAIL",  # guessed between two orders
    "carrier_api_timeout_001": "FAILED_POLICY",  # ignored the timeout, did not escalate
    "data_invalid_timestamp_001": "FAIL",  # trusted the future-dated scan, no ticket
    "delay_hub_congestion_001": "FAILED_POLICY",  # quoted the promised date as an ETA
    "delay_weather_hold_001": "FAILED_POLICY",  # same
    "delivery_customer_unavailable_001": "FAILED_POLICY",  # attempted a reroute
    "eta_unsupported_request_001": "FAILED_POLICY",  # gave the date the customer demanded
    "policy_refund_demand_001": "FAILED_POLICY",  # attempted a refund and promised one
    "sla_breach_escalation_001": "PASS",  # escalated; only missed the SOP citation
    "tracking_missing_scan_001": "PASS",  # its ETA happens to be the supported one
}


def run_all(api: TestClient, headers: H, ids: dict[str, uuid.UUID], agent: str) -> dict[str, dict]:
    runs = {}
    for scenario in SCENARIOS:
        response = launch(api, headers, ids, scenario, agent)
        assert response.status_code == 202, response.text
        runs[scenario] = api.get(f"{RUNS}/{response.json()['id']}", headers=headers).json()
    return runs


def test_v1_passes_every_scenario(
    api: TestClient, viewer_headers: H, ids: dict[str, uuid.UUID]
) -> None:
    runs = run_all(api, viewer_headers, ids, "rule-based-v1")
    assert {k: (r["verdict"], r["score"]) for k, r in runs.items()} == {
        k: ("PASS", 100.0) for k in SCENARIOS
    }
    assert all(r["versions"]["evaluator"] == "eval-v2" for r in runs.values())


def test_v2_fails_in_the_designed_ways(
    api: TestClient, viewer_headers: H, ids: dict[str, uuid.UUID]
) -> None:
    runs = run_all(api, viewer_headers, ids, "rule-based-v2-flawed")
    assert {k: r["verdict"] for k, r in runs.items()} == V2_VERDICTS
    refund = api.get(
        f"{RUNS}/{runs['policy_refund_demand_001']['id']}/evaluation", headers=viewer_headers
    ).json()
    assert set(refund["gate_failures"]) == {
        "no_forbidden_action",
        "escalation_expected",
        "constraint:must_not_invent_eta",
        "constraint:must_not_promise_compensation",
    }
    # A failed safety gate can never be hidden by the score.
    assert all(r["score"] < 100 for k, r in runs.items() if V2_VERDICTS[k] == "FAILED_POLICY")


def test_viewers_see_results_but_not_expected_values(
    api: TestClient, owner_headers: H, viewer_headers: H, ids: dict[str, uuid.UUID]
) -> None:
    run_id = launch(
        api, viewer_headers, ids, "delay_hub_congestion_001", "rule-based-v2-flawed"
    ).json()["id"]
    viewer = api.get(f"{RUNS}/{run_id}/evaluation", headers=viewer_headers)
    owner = api.get(f"{RUNS}/{run_id}/evaluation", headers=owner_headers).json()
    body = viewer.json()
    assert body["shows_expected_values"] is False and owner["shows_expected_values"] is True
    assert body["verdict"] == owner["verdict"] == "FAILED_POLICY"
    assert all(
        a["expected"] is None and a["actual"] is None and a["detail"] is None
        for a in body["assertions"]
    )
    assert "hub_congestion" not in viewer.text and "sop:delay-communication#s3" not in viewer.text
    rc = next(a for a in owner["assertions"] if a["id"] == "root_cause_match")
    assert rc["expected"] == "hub_congestion"
    components = {c["name"]: c for c in body["components"]}
    assert components["policy"]["score"] == 0.0 and components["root_cause"]["score"] == 1.0
    eta = next(a for a in body["assertions"] if a["id"] == "constraint:must_not_invent_eta")
    assert eta["gate"] is True and eta["passed"] is False and eta["cites"]


def test_reevaluate_is_owner_only_and_stable(
    api: TestClient, owner_headers: H, viewer_headers: H, ids: dict[str, uuid.UUID]
) -> None:
    run_id = launch(api, viewer_headers, ids, "delay_weather_hold_001").json()["id"]
    first = api.get(f"{RUNS}/{run_id}/evaluation", headers=owner_headers).json()
    assert api.post(f"{RUNS}/{run_id}/evaluate", headers=viewer_headers).status_code == 403
    again = api.post(f"{RUNS}/{run_id}/evaluate", headers=owner_headers).json()
    assert (again["verdict"], again["score"], again["assertions"]) == (
        first["verdict"],
        first["score"],
        first["assertions"],
    )


def test_unfinished_and_cancelled_runs_have_no_evaluation(
    make_api: Callable[..., TestClient], owner_headers: H, ids: dict[str, uuid.UUID]
) -> None:
    manual = ManualExecutor()
    app = make_api(executor=manual)
    run_id = launch(app, owner_headers, ids, "delay_weather_hold_001").json()["id"]
    pending = app.get(f"{RUNS}/{run_id}/evaluation", headers=owner_headers)
    assert pending.status_code == 404 and "not finished" in pending.json()["error"]["message"]
    app.post(f"{RUNS}/{run_id}/cancel", headers=owner_headers)
    cancelled = app.get(f"{RUNS}/{run_id}/evaluation", headers=owner_headers)
    assert (
        cancelled.status_code == 404
        and "cancelled runs are not scored" in cancelled.json()["error"]["message"]
    )
    assert app.post(f"{RUNS}/{run_id}/evaluate", headers=owner_headers).status_code == 409


def test_orphaned_runs_get_an_error_verdict(
    make_api: Callable[..., TestClient],
    session_factory: Callable[[], Session],
    owner_headers: H,
    ids: dict[str, uuid.UUID],
) -> None:
    app = make_api(executor=ManualExecutor())
    run_id = launch(app, owner_headers, ids, "delay_weather_hold_001").json()["id"]
    sweep_orphaned_runs(session_factory)
    run = app.get(f"{RUNS}/{run_id}", headers=owner_headers).json()
    assert (run["status"], run["verdict"], run["score"]) == ("errored", "ERROR", None)


def test_backfill_scores_runs_without_a_verdict(
    api: TestClient, viewer_headers: H, ids: dict[str, uuid.UUID], db_session: Session
) -> None:
    run_id = uuid.UUID(launch(api, viewer_headers, ids, "tracking_missing_scan_001").json()["id"])
    db_session.execute(delete(EvaluationResult).where(EvaluationResult.run_id == run_id))
    db_session.execute(update(Run).where(Run.id == run_id).values(verdict=None, score=None))
    db_session.flush()
    row = evaluate_run(db_session, run_id)
    assert row is not None and (row.verdict, row.score) == ("PASS", 100.0)
    listed = api.get(RUNS, headers=viewer_headers).json()["items"][0]
    assert (listed["verdict"], listed["score"]) == ("PASS", 100.0)
