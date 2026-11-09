"""Leakage guard (FR-04.3): the agent's input never contains ground truth or hints at it."""

import json
from typing import Any

from app.domain.taxonomy import RootCause
from app.schemas.scenario import ScenarioSpec
from app.services.agent_graph.agent_input import build_agent_input
from app.services.agent_graph.schemas import SUBMIT_OUTCOME


def _input_json(spec: ScenarioSpec, tools: frozenset[str]) -> dict[str, Any]:
    return build_agent_input(spec, tools).model_dump(mode="json")


def test_agent_input_never_leaks_hidden_or_hinting_content(
    scenario_files: dict[str, dict[str, Any]],
) -> None:
    for name, data in scenario_files.items():
        spec = ScenarioSpec.model_validate(data)
        agent_input = _input_json(spec, frozenset(spec.available_tools))
        # Only these fields exist: no title, category, difficulty, tags or description field.
        assert set(agent_input) == {
            "customer_message",
            "visible_context",
            "now",
            "root_cause_labels",
            "tools",
        }
        # The full root-cause label list (and the same list as the submit_outcome enum) is
        # allowed: it reveals nothing. Check everything else.
        submit_spec = agent_input["tools"][-1]
        assert submit_spec["name"] == SUBMIT_OUTCOME
        enum = submit_spec["parameters"]["$defs"]["RootCause"]["enum"]
        assert set(enum) == {r.value for r in RootCause}
        without_labels = {
            **{k: v for k, v in agent_input.items() if k != "root_cause_labels"},
            "tools": agent_input["tools"][:-1],
        }
        text = json.dumps(without_labels, ensure_ascii=False)

        gt = spec.ground_truth
        forbidden = [
            "ground_truth",
            "expected_escalation",
            "required_evidence",
            "author_note",
            "fault_injection",
            "rubric",
            spec.scenario_id,
            spec.title,
            spec.description,
            *gt.required_evidence,
        ]
        if spec.evaluation.rubric:
            forbidden.append(spec.evaluation.rubric)
        if spec.author_note:
            forbidden.append(spec.author_note)
        for needle in forbidden:
            assert needle not in text, (name, needle)
        # The expected label may appear only in the generic label list, never elsewhere.
        assert gt.root_cause.value not in text, (name, gt.root_cause)
        # Mock data is reachable only through tools.
        assert "mock_data" not in text and "tracking_events" not in text.replace(
            '"get_tracking_events"', ""
        )


def test_agent_input_contents(make_scenario: Any) -> None:
    spec = ScenarioSpec.model_validate(make_scenario())
    permitted = frozenset({"get_shipment", "get_tracking_events", "search_sop"})
    agent_input = build_agent_input(spec, permitted)

    assert agent_input.customer_message == spec.customer_message
    assert agent_input.visible_context == {"shipment_id": "SHP-1042", "customer_id": "CUS-100"}
    assert agent_input.now == "2026-10-21T15:00:00+05:30"
    assert {item.label for item in agent_input.root_cause_labels} == {r.value for r in RootCause}
    names = [t["name"] for t in agent_input.tools]
    assert names == ["get_shipment", "get_tracking_events", "search_sop", SUBMIT_OUTCOME]
    submit = agent_input.tools[-1]["parameters"]
    assert set(submit["required"]) >= {"escalation", "customer_response"}
