"""Benchmark suites end to end: launch, settle, metrics and comparison (database)."""

import json
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import DEFAULT_DATA_DIR
from app.db.models import EvaluationResult, Run, SuiteRun
from app.services.benchmarks.service import SuiteService
from app.services.execution.service import LLM_RUNS_KEY, sweep_orphaned_runs, usage_today
from app.services.providers import factory
from tests.conftest import ManualExecutor
from tests.gemini_fakes import FakeGeminiClient
from tests.helpers import H
from tests.test_evaluation import SCENARIOS

pytestmark = pytest.mark.db

V1_TO_V2 = {
    "ambiguity_insufficient_evidence_001": "newly_failed",
    "carrier_api_timeout_001": "newly_failed",
    "data_invalid_timestamp_001": "newly_failed",
    "delay_hub_congestion_001": "newly_failed",
    "delay_weather_hold_001": "newly_failed",
    "delivery_customer_unavailable_001": "newly_failed",
    "eta_unsupported_request_001": "newly_failed",
    "policy_refund_demand_001": "newly_failed",
    "sla_breach_escalation_001": "still_passing",
    "tracking_missing_scan_001": "still_passing",
}
SAFETY_REGRESSIONS = {  # FAILED_POLICY under v2: a gate v1 never failed
    "carrier_api_timeout_001",
    "delay_hub_congestion_001",
    "delay_weather_hold_001",
    "delivery_customer_unavailable_001",
    "eta_unsupported_request_001",
    "policy_refund_demand_001",
}


@pytest.fixture
def suite_id(ids: dict[str, uuid.UUID], db_session: Session) -> uuid.UUID:
    spec = json.loads((DEFAULT_DATA_DIR / "suites" / "mvp-10.json").read_text(encoding="utf-8"))
    SuiteService(db_session, None).import_many([spec])  # type: ignore[arg-type]
    return next(s.id for s in SuiteService(db_session, None).list_suites())  # type: ignore[arg-type]


def launch_suite(api: TestClient, headers: H, suite: uuid.UUID, agent: uuid.UUID, repeats: int = 1):  # type: ignore[no-untyped-def]
    return api.post(
        f"/api/v1/suites/{suite}/runs",
        json={"agent_config_id": str(agent), "repeats": repeats},
        headers=headers,
    )


def completed_suite_run(api: TestClient, headers: H, suite: uuid.UUID, agent: uuid.UUID) -> dict:
    response = launch_suite(api, headers, suite, agent)
    assert response.status_code == 202, response.text
    detail = api.get(f"/api/v1/suite-runs/{response.json()['id']}", headers=headers).json()
    assert detail["status"] == "completed", detail
    return detail


def compare(api: TestClient, headers: H, base: str, cand: str) -> dict:
    response = api.get(
        "/api/v1/comparisons",
        params={"baseline_suite_run_id": base, "candidate_suite_run_id": cand},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- golden: the MVP suite with both rule-based agents -----------------------------------------


def test_mvp_suite_v1_vs_v2_matches_the_golden_classification(
    api: TestClient, viewer_headers: H, ids: dict[str, uuid.UUID], suite_id: uuid.UUID
) -> None:
    v1 = completed_suite_run(api, viewer_headers, suite_id, ids["rule-based-v1"])
    v2 = completed_suite_run(api, viewer_headers, suite_id, ids["rule-based-v2-flawed"])
    assert v1["progress"]["done"] == v1["total_runs"] == 10
    assert sorted(r["scenario_key"] for r in v1["results"]) == sorted(SCENARIOS)

    m1, m2 = v1["metrics"], v2["metrics"]
    assert (m1["task_success_rate"], m1["root_cause_accuracy"], m1["policy_violation_rate"]) == (
        1.0,
        1.0,
        0.0,
    )
    assert (m2["task_success_rate"], m2["root_cause_accuracy"], m2["policy_violation_rate"]) == (
        0.2,
        0.7,
        0.6,
    )
    assert m1["evidence_recall"] == 1.0 and m2["evidence_recall"] < 1.0
    assert m1["escalation_recall"] == 1.0 and m2["escalation_recall"] < 1.0
    assert m1["mean_tokens"] == 0.0  # rule-based agents use no LLM tokens
    assert m1["estimated_cost_usd"] is None and m1["p95_latency_ms"] is None
    assert v1["evaluator_version"] == v2["evaluator_version"] == "eval-v2"

    forward = compare(api, viewer_headers, v1["id"], v2["id"])
    assert {p["scenario_key"]: p["pair_class"] for p in forward["pairs"]} == V1_TO_V2
    assert {p["scenario_key"] for p in forward["pairs"] if p["safety_regression"]} == (
        SAFETY_REGRESSIONS
    )
    assert forward["counts"] == {
        "fixed": 0,
        "newly_failed": 8,
        "still_passing": 2,
        "still_failing": 0,
        "not_comparable": 0,
    }
    assert forward["regression_rate"] == 0.8 and forward["safety_regressions"] == 6
    assert forward["metric_deltas"]["task_success_rate"] == -0.8

    backward = compare(api, viewer_headers, v2["id"], v1["id"])
    assert backward["counts"]["fixed"] == 8 and backward["safety_regressions"] == 0
    assert backward["regression_rate"] == 0.0


def test_comparison_is_read_only_and_flags_version_mismatches(
    api: TestClient,
    owner_headers: H,
    ids: dict[str, uuid.UUID],
    suite_id: uuid.UUID,
    db_session: Session,
) -> None:
    base = completed_suite_run(api, owner_headers, suite_id, ids["rule-based-v1"])
    cand = completed_suite_run(api, owner_headers, suite_id, ids["rule-based-v1"])

    def count(model: Any) -> int:
        return db_session.scalar(select(func.count()).select_from(model)) or 0

    before = (count(Run), count(EvaluationResult))
    clean = compare(api, owner_headers, base["id"], cand["id"])
    assert clean["counts"]["still_passing"] == 10
    assert (count(Run), count(EvaluationResult)) == before  # nothing was re-run or re-scored

    # A different scenario version and a different evaluator version: not comparable.
    hub = next(r for r in cand["results"] if r["scenario_key"] == "delay_hub_congestion_001")
    db_session.execute(
        update(Run).where(Run.id == uuid.UUID(hub["run_id"])).values(scenario_version=2)
    )
    gap = next(r for r in cand["results"] if r["scenario_key"] == "tracking_missing_scan_001")
    db_session.execute(
        update(EvaluationResult)
        .where(EvaluationResult.run_id == uuid.UUID(gap["run_id"]))
        .values(evaluator_version="eval-v1")
    )
    mixed = compare(api, owner_headers, base["id"], cand["id"])
    reasons = {
        p["scenario_key"]: p["reason"]
        for p in mixed["pairs"]
        if p["pair_class"] == "not_comparable"
    }
    assert set(reasons) == {"delay_hub_congestion_001", "tracking_missing_scan_001"}
    assert "scenario version differs" in reasons["delay_hub_congestion_001"]
    assert "evaluator version differs" in reasons["tracking_missing_scan_001"]
    assert mixed["counts"]["not_comparable"] == 2


# --- launching ---------------------------------------------------------------------------------


def test_repeats_create_one_run_per_scenario_and_repeat(
    api: TestClient, viewer_headers: H, ids: dict[str, uuid.UUID], suite_id: uuid.UUID
) -> None:
    response = launch_suite(api, viewer_headers, suite_id, ids["rule-based-v1"], repeats=2)
    detail = api.get(f"/api/v1/suite-runs/{response.json()['id']}", headers=viewer_headers).json()
    assert detail["total_runs"] == 20 and len(detail["results"]) == 20
    assert {r["repeat_index"] for r in detail["results"]} == {0, 1}
    assert detail["flaky"] == []  # rule-based agents are deterministic
    assert detail["metrics"]["runs"] == 20
    bad = launch_suite(api, viewer_headers, suite_id, ids["rule-based-v1"], repeats=4)
    assert bad.status_code == 422


def test_launch_is_all_or_nothing(
    make_api: Callable[..., TestClient],
    owner_headers: H,
    viewer_headers: H,
    ids: dict[str, uuid.UUID],
    suite_id: uuid.UUID,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def runs() -> int:
        return db_session.scalar(select(func.count()).select_from(Run)) or 0

    small_queue = make_api(max_queued_runs=5)
    full = launch_suite(small_queue, owner_headers, suite_id, ids["rule-based-v1"])
    assert full.status_code == 429 and full.json()["error"]["code"] == "run_queue_full"
    assert runs() == 0

    gemini = ids["gemini-flash-v1"]
    no_key = launch_suite(make_api(), owner_headers, suite_id, gemini)
    assert no_key.status_code == 409
    assert launch_suite(make_api(), viewer_headers, suite_id, gemini).status_code == 403

    monkeypatch.setattr(factory, "_gemini_client", lambda api_key: FakeGeminiClient([]))
    capped = make_api(gemini_api_key=SecretStr("k"), llm_daily_run_cap=5)
    short = launch_suite(capped, owner_headers, suite_id, gemini)
    assert short.status_code == 429 and short.json()["error"]["code"] == "llm_daily_cap_reached"
    assert "needs 10 LLM runs but only 5" in short.json()["error"]["message"]
    assert runs() == 0 and usage_today(db_session, LLM_RUNS_KEY) == 0


def test_cancel_stops_every_queued_run(
    make_api: Callable[..., TestClient],
    viewer_headers: H,
    ids: dict[str, uuid.UUID],
    suite_id: uuid.UUID,
) -> None:
    executor = ManualExecutor()
    api = make_api(executor=executor)
    suite_run = launch_suite(api, viewer_headers, suite_id, ids["rule-based-v1"]).json()
    assert suite_run["status"] == "queued" and suite_run["progress"]["queued"] == 10

    cancelled = api.post(f"/api/v1/suite-runs/{suite_run['id']}/cancel", headers=viewer_headers)
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    assert body["status"] == "cancelled" and body["progress"].get("cancelled") == 10
    assert body["metrics"]["evaluated"] == 0
    again = api.post(f"/api/v1/suite-runs/{suite_run['id']}/cancel", headers=viewer_headers)
    assert again.status_code == 409


def test_a_restart_settles_interrupted_suite_runs(
    make_api: Callable[..., TestClient],
    owner_headers: H,
    ids: dict[str, uuid.UUID],
    suite_id: uuid.UUID,
    session_factory: Callable[[], Session],
    db_session: Session,
) -> None:
    api = make_api(executor=ManualExecutor())
    suite_run_id = launch_suite(api, owner_headers, suite_id, ids["rule-based-v1"]).json()["id"]
    assert sweep_orphaned_runs(session_factory) == 10
    row = db_session.get(SuiteRun, uuid.UUID(suite_run_id))
    db_session.refresh(row)
    assert row is not None and row.status == "completed"
    metrics = (row.summary_json or {})["metrics"]
    assert (metrics["errors"], metrics["evaluated"], metrics["infra_error_rate"]) == (10, 0, 1.0)


# --- suites CRUD -------------------------------------------------------------------------------


def test_suite_crud_tag_suites_and_archive(
    api: TestClient, owner_headers: H, viewer_headers: H, ids: dict[str, uuid.UUID]
) -> None:
    body = {"name": "escalations", "title": "Escalation cases", "tag": "escalation"}
    assert api.post("/api/v1/suites", json=body, headers=viewer_headers).status_code == 403
    created = api.post("/api/v1/suites", json=body, headers=owner_headers)
    assert created.status_code == 201, created.text
    suite = created.json()
    assert sorted(s["scenario_key"] for s in suite["resolved"]) == [
        "carrier_api_timeout_001",
        "policy_refund_demand_001",
        "sla_breach_escalation_001",
    ]
    duplicate = api.post("/api/v1/suites", json=body, headers=owner_headers)
    assert duplicate.status_code == 409

    unknown = {"name": "bad-suite", "title": "Bad", "scenario_keys": ["nope_001"]}
    assert api.post("/api/v1/suites", json=unknown, headers=owner_headers).status_code == 422
    both = {"name": "bad-suite", "title": "Bad", "tag": "x1", "scenario_keys": ["a"]}
    assert api.post("/api/v1/suites", json=both, headers=owner_headers).status_code == 422

    edited = api.put(
        f"/api/v1/suites/{suite['id']}",
        json={
            "name": "escalations",
            "title": "Two cases",
            "scenario_keys": ["sla_breach_escalation_001", "carrier_api_timeout_001"],
        },
        headers=owner_headers,
    )
    assert edited.status_code == 200 and len(edited.json()["resolved"]) == 2

    archived = api.post(f"/api/v1/suites/{suite['id']}/archive", headers=owner_headers)
    assert archived.json()["status"] == "archived"
    blocked = launch_suite(api, owner_headers, uuid.UUID(suite["id"]), ids["rule-based-v1"])
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "suite_archived"
