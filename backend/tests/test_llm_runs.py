"""Gemini-backed runs through the real run service, worker, trace and evaluator.

The google-genai client is replaced by a scripted fake, so these tests never call the API.
"""

import json
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Run, TraceEvent
from app.services.execution.service import LLM_RUNS_KEY, usage_today
from app.services.providers import factory
from tests.gemini_fakes import (
    SIGNATURE,
    THOUGHT_TEXT,
    FakeGeminiClient,
    api_error,
    fcall,
    response,
    thought,
)
from tests.helpers import RUNS, launch, trace

pytestmark = pytest.mark.db

H = dict[str, str]
AGENT = "gemini-flash-v1"
SCENARIO = "delay_hub_congestion_001"

GOOD_OUTCOME = {
    "root_cause": "hub_congestion",
    "confidence": 0.8,
    "evidence_ids": ["event:SHP-1042:05"],
    "action_summary": ["Checked the tracking events"],
    "escalation": False,
    "customer_response": "Your parcel is delayed by congestion at the sorting hub. "
    "We are monitoring it and will update you.",
}


@pytest.fixture
def use_fake_gemini(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[Any]], FakeGeminiClient]:
    def install(script: list[Any]) -> FakeGeminiClient:
        client = FakeGeminiClient(script)
        monkeypatch.setattr(factory, "_gemini_client", lambda api_key: client)
        return client

    return install


@pytest.fixture
def gemini_api(make_api: Callable[..., TestClient]) -> Iterator[Callable[..., TestClient]]:
    def build(**overrides: Any) -> TestClient:
        return make_api(gemini_api_key=SecretStr("test-key"), gemini_rpm_limit=1000, **overrides)

    yield build


def good_script() -> list[Any]:
    return [
        response(thought(), fcall("get_tracking_events", {"shipment_id": "SHP-1042"}, signed=True)),
        response(thought(), fcall("submit_outcome", GOOD_OUTCOME, signed=True)),
    ]


def test_without_a_key_llm_runs_are_refused_clearly(
    api: TestClient, owner_headers: H, viewer_headers: H, ids: dict[str, uuid.UUID]
) -> None:
    owner = launch(api, owner_headers, ids, SCENARIO, AGENT)
    assert owner.status_code == 409
    assert owner.json()["error"]["code"] == "provider_not_configured"
    assert "GEMINI_API_KEY" in owner.json()["error"]["message"]
    assert launch(api, viewer_headers, ids, SCENARIO, AGENT).status_code == 403

    providers = {
        p["provider"]: p for p in api.get("/api/v1/agents/providers", headers=owner_headers).json()
    }
    assert providers["gemini"]["configured"] is False and providers["gemini"]["available"] is False


def test_viewers_cannot_launch_llm_runs_even_with_a_key(
    gemini_api: Callable[..., TestClient], viewer_headers: H, ids: dict[str, uuid.UUID]
) -> None:
    response = launch(gemini_api(), viewer_headers, ids, SCENARIO, AGENT)
    assert response.status_code == 403 and response.json()["error"]["code"] == "forbidden"


def test_gemini_run_completes_is_scored_and_stores_no_thoughts(
    gemini_api: Callable[..., TestClient],
    owner_headers: H,
    ids: dict[str, uuid.UUID],
    db_session: Session,
    use_fake_gemini: Callable[[list[Any]], FakeGeminiClient],
) -> None:
    client = use_fake_gemini(good_script())
    api = gemini_api()
    created = launch(api, owner_headers, ids, SCENARIO, AGENT)
    assert created.status_code == 202, created.text
    run_id = created.json()["id"]

    run = api.get(f"{RUNS}/{run_id}", headers=owner_headers).json()
    assert (run["status"], run["stop_reason"]) == ("completed", "completed")
    assert run["root_cause"] == "hub_congestion"
    assert run["verdict"] in {"PASS", "FAIL", "FAILED_POLICY"}  # scored, not ERROR
    assert run["versions"]["model"] == "gemini-3.5-flash"
    assert run["usage"] == {
        "model_calls": 2,
        "input_tokens": 200,
        "output_tokens": 40,
        "thinking_tokens": 14,
    }
    assert len(client.models.requests) == 2
    assert usage_today(db_session, LLM_RUNS_KEY) == 1

    events = trace(api, owner_headers, run_id)
    turns = [e for e in events if e["event_type"] == "agent_turn"]
    assert [t["output"]["model_id"] for t in turns] == ["gemini-3.5-flash"] * 2
    assert turns[0]["usage"]["thinking_tokens"] == 7

    # Nothing persisted anywhere carries the thought text or the signature.
    stored = db_session.scalars(
        select(TraceEvent).where(TraceEvent.run_id == uuid.UUID(run_id))
    ).all()
    row = db_session.get(Run, uuid.UUID(run_id))
    assert row is not None
    blob = json.dumps(
        [[e.input_json, e.output_json, e.error_json, e.usage_json] for e in stored]
        + [row.final_outcome_json, row.actions_json, row.error_json, row.usage_json],
        default=str,
    )
    assert THOUGHT_TEXT not in blob and SIGNATURE.decode() not in blob
    assert "thought" not in blob.replace("thinking_tokens", "")

    evaluation = api.get(f"{RUNS}/{run_id}/evaluation", headers=owner_headers)
    assert evaluation.status_code == 200 and evaluation.json()["verdict"] == run["verdict"]


def test_provider_quota_error_ends_the_run_as_an_infra_error(
    gemini_api: Callable[..., TestClient],
    owner_headers: H,
    ids: dict[str, uuid.UUID],
    use_fake_gemini: Callable[[list[Any]], FakeGeminiClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.providers.gemini.BACKOFF_S", (0.0, 0.0))
    use_fake_gemini([api_error(429, "RESOURCE_EXHAUSTED", "Quota exceeded for requests")])
    api = gemini_api()
    run_id = launch(api, owner_headers, ids, SCENARIO, AGENT).json()["id"]

    run = api.get(f"{RUNS}/{run_id}", headers=owner_headers).json()
    assert run["error"] is None or run["error"].get("code") != "platform_error", run["error"]
    assert (run["status"], run["stop_reason"], run["error_kind"]) == (
        "errored",
        "provider_error",
        "infra",
    )
    assert run["error"]["code"] == "provider_quota", run["error"]
    assert run["error"]["status"] == 429
    assert run["verdict"] == "ERROR"  # excluded from agent metrics
    types = [e["event_type"] for e in trace(api, owner_headers, run_id)]
    assert "run_error" in types and types[-1] == "run_finished"


def test_daily_llm_cap_is_enforced_without_creating_runs(
    gemini_api: Callable[..., TestClient],
    owner_headers: H,
    ids: dict[str, uuid.UUID],
    db_session: Session,
    use_fake_gemini: Callable[[list[Any]], FakeGeminiClient],
) -> None:
    use_fake_gemini(good_script())
    api = gemini_api(llm_daily_run_cap=1)
    providers = {
        p["provider"]: p for p in api.get("/api/v1/agents/providers", headers=owner_headers).json()
    }
    assert providers["gemini"]["available"] is True
    assert providers["gemini"]["runs_left_today"] == 1 and providers["gemini"]["daily_cap"] == 1

    assert launch(api, owner_headers, ids, SCENARIO, AGENT).status_code == 202
    before = db_session.scalar(select(func.count()).select_from(Run))
    refused = launch(api, owner_headers, ids, SCENARIO, AGENT)
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "llm_daily_cap_reached"
    assert db_session.scalar(select(func.count()).select_from(Run)) == before
    assert usage_today(db_session, LLM_RUNS_KEY) == 1

    # Rule-based runs never count against the LLM cap.
    assert launch(api, owner_headers, ids, SCENARIO).status_code == 202
    assert usage_today(db_session, LLM_RUNS_KEY) == 1
    left = {
        p["provider"]: p for p in api.get("/api/v1/agents/providers", headers=owner_headers).json()
    }
    assert left["gemini"]["runs_left_today"] == 0
