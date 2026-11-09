"""The LangGraph agent loop, driven by a scripted FakeProvider (no LLM, no database)."""

from collections.abc import Callable
from typing import Any

from app.schemas.scenario import ScenarioSpec
from app.services.agent_graph.agent_input import build_agent_input
from app.services.agent_graph.deciders import FakeProvider, LLMDecider, call
from app.services.agent_graph.graph import AgentLimits, AgentRunResult, run_agent
from app.services.agent_graph.schemas import ModelTurn, Usage
from app.services.tools.data_view import ScenarioDataView
from app.services.tools.gateway import ToolGateway

Factory = Callable[..., dict[str, Any]]

VALID_OUTCOME = {
    "root_cause": "hub_congestion",
    "evidence_ids": ["event:SHP-1042:05"],
    "escalation": False,
    "customer_response": "Your parcel is delayed by congestion at the Pune hub.",
}


class NoSops:
    def search(self, query: str, allowed: frozenset[str], top_k: int) -> list[Any]:
        return []


def run(
    data: dict[str, Any],
    turns: list[ModelTurn],
    *,
    limits: AgentLimits | None = None,
    max_tool_calls: int = 10,
) -> tuple[AgentRunResult, FakeProvider]:
    spec = ScenarioSpec.model_validate(data)
    gateway = ToolGateway.for_scenario(
        ScenarioDataView.from_spec(spec),
        NoSops(),
        sleep=lambda s: None,
        max_tool_calls=max_tool_calls,
    )
    provider = FakeProvider(turns)
    result = run_agent(
        build_agent_input(spec, gateway.permitted_tools),
        LLMDecider(provider),
        gateway,
        system_prompt="You are a test agent.",
        limits=limits or AgentLimits(max_steps=6),
    )
    return result, provider


def submit(arguments: dict[str, Any] | None = None) -> ModelTurn:
    return ModelTurn(tool_calls=[call("submit_outcome", arguments or VALID_OUTCOME)])


def test_tool_calls_then_valid_outcome_completes(make_scenario: Factory) -> None:
    result, _ = run(
        make_scenario(),
        [
            ModelTurn(
                tool_calls=[call("get_tracking_events", {"shipment_id": "SHP-1042"})],
                usage=Usage(input_tokens=120, output_tokens=15),
            ),
            submit(),
        ],
    )
    assert result.stop_reason == "completed"
    assert result.outcome is not None and result.outcome.root_cause == "hub_congestion"
    assert result.steps == 2
    assert [c.tool for c in result.tool_calls] == ["get_tracking_events"]
    assert result.usage == [{"input_tokens": 120, "output_tokens": 15}]
    roles = [m["role"] for m in result.messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]


def test_looping_agent_is_stopped_by_the_step_limit(make_scenario: Factory) -> None:
    looping = ModelTurn(tool_calls=[call("get_shipment", {"shipment_id": "SHP-1042"})])
    result, provider = run(make_scenario(), [looping], limits=AgentLimits(max_steps=4))
    assert result.stop_reason == "step_limit"
    assert result.outcome is None
    assert result.steps == 4 and provider.calls == 4
    assert len(result.tool_calls) == 4


def test_tool_budget_errors_are_returned_to_the_agent(make_scenario: Factory) -> None:
    looping = ModelTurn(tool_calls=[call("get_shipment", {"shipment_id": "SHP-1042"})])
    result, _ = run(make_scenario(), [looping], limits=AgentLimits(max_steps=5), max_tool_calls=2)
    codes = [getattr(c.outcome, "code", "ok") for c in result.tool_calls]
    assert codes == [
        "ok",
        "ok",
        "tool_budget_exceeded",
        "tool_budget_exceeded",
        "tool_budget_exceeded",
    ]


def test_malformed_outcome_gets_one_repair_turn(make_scenario: Factory) -> None:
    bad = submit({**VALID_OUTCOME, "root_cause": "aliens"})
    result, _ = run(make_scenario(), [bad, submit()])
    assert result.stop_reason == "completed"
    assert result.errors and result.errors[0]["type"] == "invalid_outcome"
    repair = [m for m in result.messages if m.get("name") == "submit_outcome"]
    assert repair and "root_cause" in repair[0]["content"]


def test_outcome_still_malformed_after_repair(make_scenario: Factory) -> None:
    bad = submit({"customer_response": ""})
    result, _ = run(make_scenario(), [bad])
    assert result.stop_reason == "malformed_output"
    assert result.outcome is None
    assert len(result.errors) == 2


def test_text_only_turn_gets_a_nudge(make_scenario: Factory) -> None:
    result, _ = run(make_scenario(), [ModelTurn(text="Let me think."), submit()])
    assert result.stop_reason == "completed"
    assert any(m["role"] == "user" and "submit_outcome" in m["content"] for m in result.messages)


def test_calls_made_alongside_submit_are_executed_first(make_scenario: Factory) -> None:
    turn = ModelTurn(
        tool_calls=[
            call(
                "request_escalation", {"reason": "Customer asked twice already", "severity": "low"}
            ),
            call("submit_outcome", VALID_OUTCOME),
        ]
    )
    result, _ = run(make_scenario(), [turn])
    assert result.stop_reason == "completed"
    assert [c.tool for c in result.tool_calls] == ["request_escalation"]
    assert [a["kind"] for a in result.actions] == ["escalation"]


def test_decider_exception_is_an_agent_error(make_scenario: Factory) -> None:
    class Broken:
        name = "broken"

        def decide(self, state: Any) -> ModelTurn:
            raise RuntimeError("model exploded")

    spec = ScenarioSpec.model_validate(make_scenario())
    gateway = ToolGateway.for_scenario(ScenarioDataView.from_spec(spec), NoSops())
    result = run_agent(
        build_agent_input(spec, gateway.permitted_tools), Broken(), gateway, system_prompt="x"
    )
    assert result.stop_reason == "agent_error"
    assert result.errors[0]["message"] == "model exploded"


def test_deadline_stops_the_run(make_scenario: Factory) -> None:
    result, provider = run(make_scenario(), [submit()], limits=AgentLimits(timeout_s=-1))
    assert result.stop_reason == "timeout"
    assert provider.calls == 0


def test_unknown_tool_is_reported_not_fatal(make_scenario: Factory) -> None:
    result, _ = run(make_scenario(), [ModelTurn(tool_calls=[call("hack_the_db")]), submit()])
    assert result.stop_reason == "completed"
    assert result.tool_calls[0].outcome.code == "unknown_tool"  # type: ignore[union-attr]
