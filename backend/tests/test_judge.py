"""Advisory LLM judge: input contract, storage, limits and visibility (fake Gemini client)."""

import json
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from google.genai import types
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.db.models import EvaluationResult
from app.domain.scoring import RunFacts, TraceRecord
from app.schemas.scenario import ScenarioSpec
from app.services.evaluation.judge import LLM_JUDGE_KEY, judge_input
from app.services.evaluation.service import latest_evaluation
from app.services.execution.service import usage_today
from app.services.providers import factory
from tests.gemini_fakes import FakeGeminiClient, api_error, response
from tests.helpers import RUNS, H, launch

Factory = Callable[..., dict[str, Any]]
SCENARIO = "delay_hub_congestion_001"

GOOD = {
    "score": 0.85,
    "rationale": "Kind and clear; explains the hub delay and gives no unsupported date.",
    "evidence_refs": ["event:SHP-1042:05", "ticket:TKT-0000"],  # the second was never offered
    "uncertainty": "low",
}


def json_reply(body: Any) -> types.GenerateContentResponse:
    text = body if isinstance(body, str) else json.dumps(body)
    return response(types.Part(text=text), thinking_tokens=None)


# --- input contract (no database) --------------------------------------------------------------


def test_judge_input_holds_no_ground_truth(scenario_files: dict[str, dict[str, Any]]) -> None:
    for data in scenario_files.values():
        spec = ScenarioSpec.model_validate(data)
        record = TraceRecord(
            1,
            "tool_result",
            "get_shipment",
            {"arguments": {}},
            {"status": "in_transit"},
            None,
            ("shipment:X",),
        )
        outcome = {"customer_response": "Hello", "evidence_ids": []}
        facts = RunFacts("completed", "completed", None, (record,), outcome)
        payload = judge_input(spec, facts)
        assert set(payload) == {"rubric", "customer_message", "evidence", "reply"}
        text = json.dumps(payload)
        gt = spec.ground_truth
        assert gt.root_cause.value not in text, spec.scenario_id
        assert "expected_escalation" not in text and "required_evidence" not in text
        assert payload["reply"] == ["Hello"]


# --- API (database) ----------------------------------------------------------------------------


@pytest.fixture
def judged_api(
    make_api: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch
) -> Callable[..., tuple[TestClient, FakeGeminiClient]]:
    def build(script: list[Any], **overrides: Any) -> tuple[TestClient, FakeGeminiClient]:
        client = FakeGeminiClient(script)
        monkeypatch.setattr(factory, "_gemini_client", lambda api_key: client)
        settings = {
            "gemini_api_key": SecretStr("test-key"),
            "gemini_rpm_limit": 1000,
            "llm_judge_enabled": True,
            **overrides,
        }
        return make_api(**settings), client

    return build


def finished_run(api: TestClient, headers: H, ids: dict[str, uuid.UUID]) -> str:
    created = launch(api, headers, ids, SCENARIO)
    assert created.status_code == 202, created.text
    return created.json()["id"]


@pytest.mark.db
def test_judge_is_off_by_default_and_owner_only(
    api: TestClient, owner_headers: H, viewer_headers: H, ids: dict[str, uuid.UUID]
) -> None:
    run_id = finished_run(api, owner_headers, ids)
    off = api.post(f"{RUNS}/{run_id}/judge", headers=owner_headers)
    assert off.status_code == 409 and off.json()["error"]["code"] == "judge_disabled"
    assert api.post(f"{RUNS}/{run_id}/judge", headers=viewer_headers).status_code == 403
    evaluation = api.get(f"{RUNS}/{run_id}/evaluation", headers=owner_headers).json()
    assert evaluation["judge"] is None and evaluation["judge_available"] is False


@pytest.mark.db
def test_judge_result_is_stored_and_never_changes_the_score(
    judged_api: Callable[..., tuple[TestClient, FakeGeminiClient]],
    owner_headers: H,
    viewer_headers: H,
    ids: dict[str, uuid.UUID],
    db_session: Session,
) -> None:
    api, client = judged_api([json_reply({**GOOD, "score": 0.2})])
    run_id = finished_run(api, owner_headers, ids)
    before = api.get(f"{RUNS}/{run_id}/evaluation", headers=owner_headers).json()
    assert before["judge_available"] is True

    after = api.post(f"{RUNS}/{run_id}/judge", headers=owner_headers)
    assert after.status_code == 200, after.text
    body = after.json()
    assert (body["verdict"], body["score"]) == (before["verdict"], before["score"])
    judge = body["judge"]
    assert judge["score"] == 0.2 and judge["advisory"] is True
    assert (judge["judge_model"], judge["prompt_version"]) == ("gemini-3.5-flash", "judge_v1")
    assert judge["evidence_refs"] == ["event:SHP-1042:05"]
    assert judge["unknown_refs"] == ["ticket:TKT-0000"]
    assert judge["rubric"].startswith("Empathetic")
    assert usage_today(db_session, LLM_JUDGE_KEY) == 1

    # The request carried a JSON schema and no tools.
    config = client.models.requests[0]["config"]
    assert config.response_mime_type == "application/json" and config.tools is None
    sent = json.loads(client.models.requests[0]["contents"][0].parts[0].text)
    assert set(sent) == {"rubric", "customer_message", "evidence", "reply"}

    viewer = api.get(f"{RUNS}/{run_id}/evaluation", headers=viewer_headers).json()
    assert viewer["judge"]["score"] == 0.2 and "rationale" not in viewer["judge"]
    assert viewer["judge_available"] is False

    # Re-scoring keeps the judge result (it judged the same reply).
    rescored = api.post(f"{RUNS}/{run_id}/evaluate", headers=owner_headers).json()
    assert rescored["judge"]["score"] == 0.2


@pytest.mark.db
def test_invalid_output_gets_one_retry(
    judged_api: Callable[..., tuple[TestClient, FakeGeminiClient]],
    owner_headers: H,
    ids: dict[str, uuid.UUID],
) -> None:
    api, client = judged_api([json_reply({"score": 7}), json_reply(GOOD)])
    run_id = finished_run(api, owner_headers, ids)
    body = api.post(f"{RUNS}/{run_id}/judge", headers=owner_headers).json()
    assert body["judge"]["score"] == 0.85
    assert len(client.models.requests) == 2
    assert "not valid" in client.models.requests[1]["contents"][0].parts[0].text


@pytest.mark.db
def test_invalid_output_twice_stores_nothing(
    judged_api: Callable[..., tuple[TestClient, FakeGeminiClient]],
    owner_headers: H,
    ids: dict[str, uuid.UUID],
    db_session: Session,
) -> None:
    api, _ = judged_api([json_reply("not json at all")])
    run_id = finished_run(api, owner_headers, ids)
    failed = api.post(f"{RUNS}/{run_id}/judge", headers=owner_headers)
    assert failed.status_code == 502 and failed.json()["error"]["code"] == "judge_invalid_output"
    row = latest_evaluation(db_session, uuid.UUID(run_id))
    assert isinstance(row, EvaluationResult) and row.judge_json is None
    assert usage_today(db_session, LLM_JUDGE_KEY) == 1  # the quota was still used


@pytest.mark.db
def test_judge_daily_cap_and_provider_quota(
    judged_api: Callable[..., tuple[TestClient, FakeGeminiClient]],
    owner_headers: H,
    ids: dict[str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.providers.gemini.BACKOFF_S", (0.0, 0.0))
    api, _ = judged_api([api_error(429, "RESOURCE_EXHAUSTED")], llm_judge_daily_cap=1)
    run_id = finished_run(api, owner_headers, ids)
    quota = api.post(f"{RUNS}/{run_id}/judge", headers=owner_headers)
    assert quota.status_code == 429 and quota.json()["error"]["code"] == "provider_quota"
    capped = api.post(f"{RUNS}/{run_id}/judge", headers=owner_headers)
    assert capped.status_code == 429
    assert capped.json()["error"]["code"] == "judge_daily_cap_reached"
