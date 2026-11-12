"""Failure reports end to end: runs -> evaluation -> diag-v1 -> API (database)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import EvaluationResult, FailureReport
from tests.helpers import RUNS, H, launch
from tests.test_evaluation import SCENARIOS, run_all

pytestmark = pytest.mark.db

# The flawed agent's designed failures -> (primary failure type, all failure types).
V2_DIAGNOSES: dict[str, tuple[str | None, set[str]]] = {
    "ambiguity_insufficient_evidence_001": (
        "wrong_root_cause",  # guessed between two orders
        {"wrong_root_cause", "missing_evidence", "response_not_grounded"},
    ),
    "carrier_api_timeout_001": (
        "missed_escalation",  # ignored the timeout and did not escalate
        {
            "missed_escalation",
            "unsupported_claim",
            "tool_failure_unhandled",
            "wrong_root_cause",
            "missing_evidence",
            "response_not_grounded",
        },
    ),
    "data_invalid_timestamp_001": (
        "wrong_root_cause",  # trusted the future-dated scan, no correction ticket
        {
            "wrong_root_cause",
            "missing_evidence",
            "required_action_missing",
            "response_not_grounded",
        },
    ),
    "delay_hub_congestion_001": ("unsupported_claim", {"unsupported_claim", "missing_evidence"}),
    "delay_weather_hold_001": ("unsupported_claim", {"unsupported_claim", "missing_evidence"}),
    "delivery_customer_unavailable_001": (
        "forbidden_action",  # attempted a reroute
        {"forbidden_action", "missing_evidence"},
    ),
    "eta_unsupported_request_001": ("unsupported_claim", {"unsupported_claim", "missing_evidence"}),
    "policy_refund_demand_001": (
        "missed_escalation",  # attempted a refund, promised one, did not escalate
        {"missed_escalation", "forbidden_action", "unsupported_claim", "missing_evidence"},
    ),
    "sla_breach_escalation_001": ("missing_evidence", {"missing_evidence"}),  # PASS: SOP skipped
    "tracking_missing_scan_001": (None, set()),
}


def report(api: TestClient, headers: H, run_id: str) -> dict:
    response = api.get(f"{RUNS}/{run_id}/failure-report", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def assert_cited(body: dict) -> None:
    for item in body["items"]:
        if item["failure_type"] == "insufficient_evidence":
            continue
        assert item["assertion_ids"], item
        assert item["trace_refs"] and all(r.startswith("te:") for r in item["trace_refs"]), item


def test_v1_has_no_failures(api: TestClient, viewer_headers: H, ids: dict[str, uuid.UUID]) -> None:
    runs = run_all(api, viewer_headers, ids, "rule-based-v1")
    for scenario, run in runs.items():
        body = report(api, viewer_headers, run["id"])
        assert (body["status"], body["items"]) == ("no_failures", []), scenario
        assert body["diagnoser_version"] == "diag-v1"


def test_v2_diagnoses_match_its_designed_flaws(
    api: TestClient, owner_headers: H, ids: dict[str, uuid.UUID]
) -> None:
    runs = run_all(api, owner_headers, ids, "rule-based-v2-flawed")
    found = {}
    for scenario in SCENARIOS:
        body = report(api, owner_headers, runs[scenario]["id"])
        assert_cited(body)
        primary = [i["failure_type"] for i in body["items"] if i["primary"]]
        found[scenario] = (
            primary[0] if primary else None,
            {i["failure_type"] for i in body["items"]},
        )
        trace = api.get(f"{RUNS}/{runs[scenario]['id']}/trace", headers=owner_headers).json()
        refs = {e["ref"] for e in trace["events"]}
        assert all(r in refs for i in body["items"] for r in i["trace_refs"]), scenario
    assert found == V2_DIAGNOSES


def test_viewers_get_the_report_without_ground_truth(
    api: TestClient, viewer_headers: H, owner_headers: H, ids: dict[str, uuid.UUID]
) -> None:
    run_id = launch(
        api, viewer_headers, ids, "data_invalid_timestamp_001", "rule-based-v2-flawed"
    ).json()["id"]
    viewer = api.get(f"{RUNS}/{run_id}/failure-report", headers=viewer_headers)
    owner = report(api, owner_headers, run_id)
    body = viewer.json()
    assert body["shows_details"] is False and owner["shows_details"] is True
    assert all(i["diagnosis"] is None and i["evidence"] is None for i in body["items"])
    assert "invalid_timestamp" not in viewer.text  # the expected root cause
    wrong = next(i for i in owner["items"] if i["failure_type"] == "wrong_root_cause")
    assert "invalid_timestamp" in wrong["diagnosis"]
    assert [i["summary"] for i in body["items"]] == [i["summary"] for i in owner["items"]]


def test_reports_are_stored_once_per_evaluation(
    api: TestClient, owner_headers: H, ids: dict[str, uuid.UUID], db_session: Session
) -> None:
    run_id = launch(
        api, owner_headers, ids, "policy_refund_demand_001", "rule-based-v2-flawed"
    ).json()["id"]
    rows = lambda: db_session.scalars(  # noqa: E731
        select(FailureReport).where(FailureReport.run_id == uuid.UUID(run_id))
    ).all()
    first = len(rows())
    assert first >= 3
    assert api.post(f"{RUNS}/{run_id}/evaluate", headers=owner_headers).status_code == 200
    assert len(rows()) == first  # re-scoring replaces, never duplicates
    assert {r.failure_type for r in rows() if r.is_primary} == {"missed_escalation"}


def test_older_evaluations_are_diagnosed_on_first_read(
    api: TestClient, viewer_headers: H, ids: dict[str, uuid.UUID], db_session: Session
) -> None:
    run_id = launch(
        api, viewer_headers, ids, "delivery_customer_unavailable_001", "rule-based-v2-flawed"
    ).json()["id"]
    rid = uuid.UUID(run_id)
    db_session.query(FailureReport).filter(FailureReport.run_id == rid).delete()
    db_session.execute(
        update(EvaluationResult)
        .where(EvaluationResult.run_id == rid)
        .values(diagnoser_version=None)
    )
    body = report(api, viewer_headers, run_id)
    assert body["status"] == "diagnosed"
    assert next(i for i in body["items"] if i["primary"])["failure_type"] == "forbidden_action"


def test_platform_errors_and_unfinished_runs(
    api: TestClient, owner_headers: H, ids: dict[str, uuid.UUID], db_session: Session
) -> None:
    from app.db.models import Run
    from app.services.evaluation.service import evaluate_run

    run_id = launch(api, owner_headers, ids, "delay_hub_congestion_001").json()["id"]
    rid = uuid.UUID(run_id)
    db_session.execute(
        update(Run).where(Run.id == rid).values(status="errored", error_kind="infra")
    )
    evaluate_run(db_session, rid)
    body = report(api, owner_headers, run_id)
    assert (body["verdict"], body["status"], body["items"]) == ("ERROR", "not_diagnosed", [])

    missing = api.get(f"{RUNS}/{uuid.uuid4()}/failure-report", headers=owner_headers)
    assert missing.status_code == 404
