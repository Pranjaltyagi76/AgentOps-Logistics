"""Golden runs of both rule-based agents on every scenario (uses Postgres SOP search).

These check agent *behaviour* against the scenario design. They are not the evaluator
(Phase 5), which will score the same runs with weighted components and safety gates.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.config import DEFAULT_DATA_DIR
from app.domain.sop_corpus import load_corpus
from app.domain.taxonomy import ACTION_TOOLS
from app.schemas.agent_config import AgentConfigSpec
from app.schemas.scenario import ScenarioSpec
from app.services.agent_graph.graph import AgentRunResult
from app.services.agent_graph.runner import run_scenario
from app.services.sops.service import PostgresSopSearcher, sync_corpus

pytestmark = pytest.mark.db


def _config(name: str) -> AgentConfigSpec:
    path = next(Path(DEFAULT_DATA_DIR / "agents").glob(f"{name}.v*.json"))
    return AgentConfigSpec.model_validate(json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture
def run_all(db_session: Session, scenario_files: dict[str, dict[str, Any]]):
    sync_corpus(db_session, load_corpus(DEFAULT_DATA_DIR / "sops"))
    searcher = PostgresSopSearcher(db_session)

    def go(agent: str) -> dict[str, tuple[ScenarioSpec, AgentRunResult]]:
        config = _config(agent)
        results = {}
        for data in scenario_files.values():
            spec = ScenarioSpec.model_validate(data)
            results[spec.scenario_id] = (
                spec,
                run_scenario(spec, config, searcher, sleep=lambda s: None),
            )
        return results

    return go


def test_rule_based_v1_handles_every_scenario_as_designed(run_all) -> None:
    for scenario_id, (spec, result) in run_all("rule-based-v1").items():
        gt = spec.ground_truth
        outcome = result.outcome
        assert result.stop_reason == "completed" and outcome is not None, scenario_id
        assert outcome.root_cause == gt.root_cause, scenario_id
        assert outcome.escalation == gt.expected_escalation, scenario_id

        called = [c.tool for c in result.tool_calls]
        assert set(gt.required_tools) <= set(called), (scenario_id, called)
        assert set(gt.required_actions) <= {c.tool for c in result.tool_calls if c.ok}, scenario_id
        assert not set(gt.forbidden_actions) & set(called), scenario_id
        assert all(c.ok for c in result.tool_calls if c.tool in ACTION_TOOLS), scenario_id

        returned = {e for c in result.tool_calls if c.ok for e in c.outcome.evidence_ids}  # type: ignore[union-attr]
        assert set(gt.required_evidence) <= set(outcome.evidence_ids), scenario_id
        assert set(outcome.evidence_ids) <= returned, (scenario_id, "cited an ID no tool returned")

        reply = outcome.customer_response
        assert "event:" not in reply and "sop:" not in reply and "get_" not in reply
        if gt.supported_eta is None:
            assert "estimated delivery date of" not in reply, scenario_id


def test_rule_based_v1_is_deterministic(run_all) -> None:
    first = {k: r.outcome.model_dump() for k, (_, r) in run_all("rule-based-v1").items()}  # type: ignore[union-attr]
    second = {k: r.outcome.model_dump() for k, (_, r) in run_all("rule-based-v1").items()}  # type: ignore[union-attr]
    assert first == second


def test_rule_based_v2_flawed_fails_in_the_designed_ways(run_all) -> None:
    runs = run_all("rule-based-v2-flawed")
    for scenario_id, (_, result) in runs.items():
        assert result.stop_reason == "completed", scenario_id
        assert "search_sop" not in [c.tool for c in result.tool_calls], scenario_id

    def outcome(key: str) -> Any:
        return runs[key][1].outcome

    # Trusts the future-dated "delivered" scan and guesses between two orders.
    assert outcome("data_invalid_timestamp_001").root_cause == "delivered_confirmed"
    assert outcome("ambiguity_insufficient_evidence_001").root_cause == "delivered_confirmed"
    # Ignores the carrier timeout and does not escalate.
    assert outcome("carrier_api_timeout_001").root_cause == "in_transit_on_schedule"
    assert outcome("carrier_api_timeout_001").escalation is False
    # Quotes the promised date as an ETA where none is supported.
    assert (
        "should arrive by 23 October 2026" in outcome("delay_hub_congestion_001").customer_response
    )

    # Tries forbidden actions; the policy blocks them and the attempt is recorded.
    refund_calls = runs["policy_refund_demand_001"][1].tool_calls
    denied = [c for c in refund_calls if c.tool == "request_refund"]
    assert denied and denied[0].outcome.code == "policy_denied"  # type: ignore[union-attr]
    assert outcome("policy_refund_demand_001").escalation is False
    reroute_calls = runs["delivery_customer_unavailable_001"][1].tool_calls
    assert any(c.tool == "request_reroute" and not c.ok for c in reroute_calls)
