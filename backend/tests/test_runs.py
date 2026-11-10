"""Run lifecycle, trace persistence, caps, cancel, timeout and the orphan sweeper (database)."""

import json
import threading
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import DEFAULT_DATA_DIR
from app.db.models import AgentConfig, Run, Scenario, TraceEvent
from app.domain.sop_corpus import load_corpus
from app.services.agents.service import AgentConfigService
from app.services.execution.executor import CancelToken
from app.services.execution.service import sweep_orphaned_runs, try_consume
from app.services.execution.worker import execute_run, mark_overrun
from app.services.scenarios.service import ScenarioService
from app.services.sops.service import sync_corpus
from tests.conftest import ManualExecutor

pytestmark = pytest.mark.db

H = dict[str, str]
RUNS = "/api/v1/runs"


@pytest.fixture
def ids(
    db_session: Session, scenario_files: dict[str, dict[str, Any]], catalog: Any
) -> dict[str, uuid.UUID]:
    """Seeds SOPs, scenarios and agents into the test transaction; returns name -> row id."""
    sync_corpus(db_session, load_corpus(DEFAULT_DATA_DIR / "sops"))
    ScenarioService(db_session, catalog).import_many(list(scenario_files.values()))
    agents = [
        json.loads(p.read_text()) for p in sorted((DEFAULT_DATA_DIR / "agents").glob("*.json"))
    ]
    AgentConfigService(db_session).import_many(agents)
    result = {s.scenario_key: s.id for s in db_session.scalars(select(Scenario))}
    result |= {a.name: a.id for a in db_session.scalars(select(AgentConfig))}
    return result


def launch(
    api: TestClient,
    headers: H,
    ids: dict[str, uuid.UUID],
    scenario: str,
    agent: str = "rule-based-v1",
):  # type: ignore[no-untyped-def]
    return api.post(
        RUNS,
        json={"scenario_id": str(ids[scenario]), "agent_config_id": str(ids[agent])},
        headers=headers,
    )


def trace(api: TestClient, headers: H, run_id: str, **params: Any) -> list[dict[str, Any]]:
    response = api.get(f"{RUNS}/{run_id}/trace", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["events"]


# --- lifecycle and trace -------------------------------------------------------------------


def test_launch_runs_to_completion_with_a_complete_trace(
    api: TestClient, viewer_headers: H, ids: dict[str, uuid.UUID], db_session: Session
) -> None:
    response = launch(api, viewer_headers, ids, "delay_hub_congestion_001")
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]

    run = api.get(f"{RUNS}/{run_id}", headers=viewer_headers).json()
    assert (run["status"], run["stop_reason"]) == ("completed", "completed")
    assert run["root_cause"] == "hub_congestion" and run["escalation"] is False
    assert run["outcome"]["customer_response"]
    assert run["tool_call_count"] == 4 and run["steps"] == 5
    assert run["latency_ms"] is not None and run["started_at"] and run["finished_at"]
    assert run["triggered_by_role"] == "viewer"
    assert run["limits"] == {"max_steps": 12, "max_tool_calls": 10, "timeout_s": 30}
    assert (
        run["versions"]["policy"] == "policy-v1" and run["versions"]["tool_registry"] == "tools-v1"
    )
    assert run["verdict"] is None and run["score"] is None  # evaluator arrives in Phase 5

    events = trace(api, viewer_headers, run_id)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert run["trace_event_count"] == len(events)
    types = [e["event_type"] for e in events]
    assert types[:3] == ["run_started", "agent_input", "agent_turn"]
    assert types[-2:] == ["outcome_submitted", "run_finished"]
    tools = [e["tool"] for e in events if e["event_type"] == "tool_result"]
    assert tools == ["get_shipment", "get_tracking_events", "get_carrier_status", "search_sop"]
    assert events[0]["ref"] == "te:1"
    submitted = next(e for e in events if e["event_type"] == "outcome_submitted")
    assert "event:SHP-1042:05" in submitted["evidence_ids"]

    # The exact versions used are now locked; editing them creates new versions.
    assert db_session.get(Scenario, ids["delay_hub_congestion_001"]).is_locked  # type: ignore[union-attr]
    assert db_session.get(AgentConfig, ids["rule-based-v1"]).is_locked  # type: ignore[union-attr]


def test_trace_survives_a_new_app_instance(
    api: TestClient,
    make_api: Callable[..., TestClient],
    viewer_headers: H,
    ids: dict[str, uuid.UUID],
) -> None:
    run_id = launch(api, viewer_headers, ids, "delay_weather_hold_001").json()["id"]
    before = trace(api, viewer_headers, run_id)
    restarted = make_api()  # a fresh app, as after a server restart
    token = restarted.post("/api/v1/auth/demo").json()["access_token"]
    after = trace(restarted, {"Authorization": f"Bearer {token}"}, run_id)
    assert after == before


def test_trace_polling_after_seq_and_pii_masking(
    api: TestClient, viewer_headers: H, ids: dict[str, uuid.UUID]
) -> None:
    run_id = launch(api, viewer_headers, ids, "delay_hub_congestion_001").json()["id"]
    later = trace(api, viewer_headers, run_id, after_seq=5)
    assert later and all(e["seq"] > 5 for e in later)

    shipment = next(e for e in trace(api, viewer_headers, run_id) if e["tool"] == "get_shipment")
    assert shipment["output"]["recipient_name"] == "A***** R**"  # stored unmasked, shown masked
    assert shipment["input"]["arguments"] == {"shipment_id": "SHP-1042"}


def test_agent_input_event_contains_no_ground_truth(
    api: TestClient, viewer_headers: H, ids: dict[str, uuid.UUID], scenario_files: dict[str, Any]
) -> None:
    run_id = launch(api, viewer_headers, ids, "sla_breach_escalation_001").json()["id"]
    agent_input = next(
        e for e in trace(api, viewer_headers, run_id) if e["event_type"] == "agent_input"
    )
    text = json.dumps(agent_input["input"])
    gt = scenario_files["sla_breach_escalation_001.v1.json"]["ground_truth"]
    for evidence_id in gt["required_evidence"]:
        assert evidence_id not in text
    assert "ground_truth" not in text and "sla_breach_escalation_001" not in text


def test_policy_denied_attempts_are_traced(
    api: TestClient, viewer_headers: H, ids: dict[str, uuid.UUID]
) -> None:
    run_id = launch(
        api, viewer_headers, ids, "policy_refund_demand_001", "rule-based-v2-flawed"
    ).json()["id"]
    denied = [e for e in trace(api, viewer_headers, run_id) if e["event_type"] == "policy_denied"]
    assert len(denied) == 1 and denied[0]["tool"] == "request_refund"
    assert denied[0]["error"]["details"]["rule_id"] == "policy-v1/refund-requires-authorization"


def test_tool_errors_are_traced(
    session_factory: Callable[[], Session],
    make_api: Callable[..., TestClient],
    viewer_headers: H,
    ids: dict[str, uuid.UUID],
) -> None:
    # Run the carrier-timeout scenario on a manual executor so simulated latency can be skipped.
    manual = ManualExecutor()
    app = make_api(executor=manual)
    run_id = launch(app, viewer_headers, ids, "carrier_api_timeout_001").json()["id"]
    token = manual.tokens[uuid.UUID(run_id)]
    token.wait = lambda seconds: None  # type: ignore[method-assign]
    manual.run_pending()
    errors = [e for e in trace(app, viewer_headers, run_id) if e["event_type"] == "tool_error"]
    assert [e["error"]["code"] for e in errors] == ["timeout", "timeout"]
    assert errors[0]["input"]["simulated_latency_ms"] == 3000
    assert app.get(f"{RUNS}/{run_id}", headers=viewer_headers).json()["escalation"] is True


# --- access and caps -----------------------------------------------------------------------


def test_llm_agents_are_not_runnable_yet(
    api: TestClient,
    owner_headers: H,
    viewer_headers: H,
    ids: dict[str, uuid.UUID],
    db_session: Session,
) -> None:
    gemini = AgentConfigService(db_session).create(
        {"name": "gemini-test", "provider": "gemini", "model_id": "gemini-flash-latest"}
    )
    body = {"scenario_id": str(ids["delay_hub_congestion_001"]), "agent_config_id": str(gemini.id)}
    owner = api.post(RUNS, json=body, headers=owner_headers)
    assert owner.status_code == 409 and owner.json()["error"]["code"] == "provider_not_available"
    assert api.post(RUNS, json=body, headers=viewer_headers).status_code == 403


def test_unknown_and_archived_inputs_are_rejected(
    api: TestClient, viewer_headers: H, ids: dict[str, uuid.UUID], db_session: Session
) -> None:
    body = {"scenario_id": str(uuid.uuid4()), "agent_config_id": str(ids["rule-based-v1"])}
    assert api.post(RUNS, json=body, headers=viewer_headers).status_code == 404
    db_session.execute(
        update(Scenario)
        .where(Scenario.scenario_key == "delay_weather_hold_001")
        .values(status="archived")
    )
    db_session.flush()
    archived = launch(api, viewer_headers, ids, "delay_weather_hold_001")
    assert archived.status_code == 409 and archived.json()["error"]["code"] == "scenario_archived"
    assert api.post(RUNS, json={"scenario_id": "x"}, headers=viewer_headers).status_code == 422
    assert api.get(f"{RUNS}/{uuid.uuid4()}", headers=viewer_headers).status_code == 404


def test_run_creation_is_rate_limited(
    make_api: Callable[..., TestClient], ids: dict[str, uuid.UUID]
) -> None:
    app = make_api(run_rate_limit_per_minute=2)
    headers = {"Authorization": f"Bearer {app.post('/api/v1/auth/demo').json()['access_token']}"}
    codes = [launch(app, headers, ids, "delay_weather_hold_001").status_code for _ in range(3)]
    assert codes == [202, 202, 429]


def test_queue_cap(make_api: Callable[..., TestClient], ids: dict[str, uuid.UUID]) -> None:
    app = make_api(executor=ManualExecutor(), max_queued_runs=2)
    headers = {"Authorization": f"Bearer {app.post('/api/v1/auth/demo').json()['access_token']}"}
    codes = [launch(app, headers, ids, "delay_weather_hold_001").status_code for _ in range(3)]
    assert codes == [202, 202, 429]


# --- cancel, timeout, watchdog -------------------------------------------------------------


def test_cancel_a_queued_run(
    make_api: Callable[..., TestClient],
    owner_headers: H,
    viewer_headers: H,
    ids: dict[str, uuid.UUID],
) -> None:
    manual = ManualExecutor()
    app = make_api(executor=manual)
    run_id = launch(app, owner_headers, ids, "delay_weather_hold_001").json()["id"]
    assert app.get(f"{RUNS}/{run_id}", headers=owner_headers).json()["status"] == "queued"

    assert (
        app.post(f"{RUNS}/{run_id}/cancel", headers=viewer_headers).status_code == 403
    )  # not theirs
    cancelled = app.post(f"{RUNS}/{run_id}/cancel", headers=owner_headers).json()
    assert cancelled["status"] == "cancelled" and cancelled["cancel_requested"] is True

    manual.run_pending()  # the job starts later and must not resurrect the run
    run = app.get(f"{RUNS}/{run_id}", headers=owner_headers).json()
    assert run["status"] == "cancelled"
    assert [e["event_type"] for e in trace(app, owner_headers, run_id)] == ["run_finished"]
    again = app.post(f"{RUNS}/{run_id}/cancel", headers=owner_headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "run_not_active"


@pytest.mark.parametrize(
    ("reason", "status"), [("cancelled", "cancelled"), ("timeout", "timed_out")]
)
def test_stopping_a_running_run(
    make_api: Callable[..., TestClient],
    session_factory: Callable[[], Session],
    viewer_headers: H,
    ids: dict[str, uuid.UUID],
    reason: str,
    status: str,
) -> None:
    manual = ManualExecutor()
    app = make_api(executor=manual)
    run_id = uuid.UUID(launch(app, viewer_headers, ids, "carrier_api_timeout_001").json()["id"])
    # Stop it while it waits on the first (3 s) simulated carrier timeout.
    token = CancelToken()
    threading.Timer(0.2, token.cancel, args=(reason,)).start()
    execute_run(run_id, token, session_factory)

    run = app.get(f"{RUNS}/{run_id}", headers=viewer_headers).json()
    assert run["status"] == status and run["stop_reason"] == reason
    assert run["outcome"] is None
    events = trace(app, viewer_headers, str(run_id))
    limit = [e for e in events if e["event_type"] == "limit_exceeded"]
    assert limit and limit[0]["output"]["reason"] == reason
    assert events[-1]["event_type"] == "run_finished"


def test_watchdog_overrun_wins_over_a_late_result(
    make_api: Callable[..., TestClient],
    session_factory: Callable[[], Session],
    viewer_headers: H,
    ids: dict[str, uuid.UUID],
    db_session: Session,
) -> None:
    manual = ManualExecutor()
    app = make_api(executor=manual)
    run_id = uuid.UUID(launch(app, viewer_headers, ids, "delay_weather_hold_001").json()["id"])
    db_session.execute(update(Run).where(Run.id == run_id).values(status="running"))
    db_session.flush()
    mark_overrun(run_id, session_factory)
    run = app.get(f"{RUNS}/{run_id}", headers=viewer_headers).json()
    assert run["status"] == "timed_out" and run["error"]["code"] == "watchdog_timeout"
    manual.run_pending()  # the stuck job "finishes" later: ignored
    assert app.get(f"{RUNS}/{run_id}", headers=viewer_headers).json()["status"] == "timed_out"


def test_sweeper_marks_orphaned_runs(
    make_api: Callable[..., TestClient],
    session_factory: Callable[[], Session],
    viewer_headers: H,
    ids: dict[str, uuid.UUID],
    db_session: Session,
) -> None:
    app = make_api(executor=ManualExecutor())
    queued = launch(app, viewer_headers, ids, "delay_weather_hold_001").json()["id"]
    running = launch(app, viewer_headers, ids, "delay_hub_congestion_001").json()["id"]
    db_session.execute(update(Run).where(Run.id == uuid.UUID(running)).values(status="running"))
    db_session.flush()

    assert sweep_orphaned_runs(session_factory) == 2
    for run_id in (queued, running):
        run = app.get(f"{RUNS}/{run_id}", headers=viewer_headers).json()
        assert (run["status"], run["error_kind"], run["error"]["code"]) == (
            "errored",
            "infra",
            "orphaned",
        )
        assert trace(app, viewer_headers, run_id)[-1]["event_type"] == "run_error"
    assert sweep_orphaned_runs(session_factory) == 0


# --- listing and counters ------------------------------------------------------------------


def test_list_runs_with_filters_and_pagination(
    api: TestClient, viewer_headers: H, ids: dict[str, uuid.UUID]
) -> None:
    for scenario in (
        "delay_hub_congestion_001",
        "delay_weather_hold_001",
        "delay_weather_hold_001",
    ):
        assert launch(api, viewer_headers, ids, scenario).status_code == 202
    page = api.get(RUNS, params={"limit": 2}, headers=viewer_headers).json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    rest = api.get(
        RUNS, params={"limit": 2, "cursor": page["next_cursor"]}, headers=viewer_headers
    ).json()
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None
    created = [i["created_at"] for i in page["items"] + rest["items"]]
    assert created == sorted(created, reverse=True)

    weather = api.get(
        RUNS, params={"scenario_key": "delay_weather_hold_001"}, headers=viewer_headers
    ).json()
    assert len(weather["items"]) == 2
    done = api.get(
        RUNS, params={"status": "completed", "agent_name": "rule-based-v1"}, headers=viewer_headers
    ).json()
    assert len(done["items"]) == 3
    assert api.get(RUNS, params={"status": "bogus"}, headers=viewer_headers).status_code == 422


def test_daily_usage_counter(db_session: Session) -> None:
    assert [try_consume(db_session, "llm_runs", 2) for _ in range(3)] == [True, True, False]
    assert try_consume(db_session, "other_key", 1) is True


def test_trace_events_are_deleted_with_their_run(
    api: TestClient, viewer_headers: H, ids: dict[str, uuid.UUID], db_session: Session
) -> None:
    run_id = uuid.UUID(launch(api, viewer_headers, ids, "delay_weather_hold_001").json()["id"])
    count = select(TraceEvent).where(TraceEvent.run_id == run_id)
    assert list(db_session.scalars(count))
    db_session.delete(db_session.get(Run, run_id))
    db_session.flush()
    assert list(db_session.scalars(count)) == []
