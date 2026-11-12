"""The candidate agent as a LangGraph state machine.

    START -> intake -> decide --(tool calls)--> act --+--> decide ...
                         |                            |
                         +--(submit_outcome)--> finalize <--+
                         +--(limit / timeout / error)--> finalize -> END

- intake:   builds the visible conversation (system prompt + agent input)
- decide:   asks the Decider for the next turn; enforces max_steps and the wall-clock deadline
- act:      executes tool calls through the ToolGateway (validation, policy, faults, budget)
- finalize: validates the submitted AgentOutcome; one repair turn if it is malformed

Only observable actions are recorded: tool calls, tool results and the visible text the decider
returns. No hidden reasoning is requested or stored (PROJECT.md §5 FR-05).
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.services.agent_graph.deciders import AgentState, Decider, Observation
from app.services.agent_graph.schemas import SUBMIT_OUTCOME, AgentInput, AgentOutcome, ModelTurn
from app.services.providers.errors import ProviderError
from app.services.tools.gateway import ToolCallRecord, ToolGateway

MAX_REPAIR_ATTEMPTS = 1
NUDGE = "Respond with tool calls, or call submit_outcome to finish the case."


@dataclass(frozen=True)
class AgentLimits:
    max_steps: int = 8
    timeout_s: float = 60.0


EventSink = Callable[[str, str | None, dict[str, Any]], None]


def _no_event(event_type: str, node: str | None, payload: dict[str, Any]) -> None:
    return None


def _never_stop() -> str | None:
    return None


@dataclass(frozen=True)
class RunHooks:
    """Lets the run executor observe the loop and stop it (Phase 4).

    - on_event(event_type, node, payload): called for agent turns, limits and outcomes
      (tool calls are observed separately through the gateway observer).
    - should_stop(): returns a stop reason ("cancelled" / "timeout") to end the run early.
    """

    on_event: EventSink = _no_event
    should_stop: Callable[[], str | None] = _never_stop


@dataclass
class AgentRunResult:
    outcome: AgentOutcome | None
    stop_reason: str
    steps: int
    tool_calls: list[ToolCallRecord]
    actions: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    duration_ms: int
    usage: list[dict[str, Any]] = field(default_factory=list)


def _turn_to_message(turn: ModelTurn) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": turn.text,
        "tool_calls": [c.model_dump(mode="json") for c in turn.tool_calls],
    }


def build_agent_graph(
    decider: Decider,
    gateway: ToolGateway,
    *,
    system_prompt: str,
    limits: AgentLimits,
    deadline: float,
    usage_log: list[dict[str, Any]],
    hooks: RunHooks | None = None,
) -> Any:
    hooks = hooks or RunHooks()

    def stop(reason: str, **details: Any) -> dict[str, Any]:
        hooks.on_event("limit_exceeded", "decide", {"reason": reason, **details})
        return {"stop_reason": reason}

    def intake(state: AgentState) -> dict[str, Any]:
        # Recorded verbatim so anyone can audit exactly what the agent was told.
        hooks.on_event("agent_input", "intake", state["input"])
        agent_input = dict(state["input"])
        tools = agent_input.pop("tools")
        user = {
            "role": "user",
            "content": json.dumps(
                {**agent_input, "available_tools": [t["name"] for t in tools]}, ensure_ascii=False
            ),
        }
        return {"messages": [{"role": "system", "content": system_prompt}, user]}

    def decide(state: AgentState) -> dict[str, Any]:
        external = hooks.should_stop()
        if external is not None:
            return stop(external)
        if time.monotonic() > deadline:
            return stop("timeout", timeout_s=limits.timeout_s)
        if state["step_count"] >= limits.max_steps:
            return stop("step_limit", max_steps=limits.max_steps)
        started = time.monotonic()
        try:
            turn = decider.decide(state)
        except ProviderError as exc:  # quota / outage / auth: the platform failed, not the agent
            external = hooks.should_stop()
            if external is not None:  # cancelled or timed out while waiting on the provider
                return stop(external)
            error = {"stage": "decide", "type": type(exc).__name__, **exc.to_dict()}
            return {"stop_reason": "provider_error", "errors": [*state["errors"], error]}
        except Exception as exc:  # the agent under test failing is a result, not a crash
            error = {"stage": "decide", "type": type(exc).__name__, "message": str(exc)[:500]}
            return {"stop_reason": "agent_error", "errors": [*state["errors"], error]}
        if turn.usage is not None:
            usage_log.append(turn.usage.model_dump())
        hooks.on_event(
            "agent_turn",
            "decide",
            {
                "step": state["step_count"] + 1,
                "text": turn.text,
                "tool_calls": [c.model_dump(mode="json") for c in turn.tool_calls],
                "usage": turn.usage.model_dump() if turn.usage else None,
                "model_id": turn.model_id,
                "duration_ms": round((time.monotonic() - started) * 1000),
            },
        )

        messages = [*state["messages"], _turn_to_message(turn)]
        outcome_calls = [c for c in turn.tool_calls if c.name == SUBMIT_OUTCOME]
        other_calls = [
            c.model_dump(mode="json") for c in turn.tool_calls if c.name != SUBMIT_OUTCOME
        ]
        update: dict[str, Any] = {
            "step_count": state["step_count"] + 1,
            "pending_calls": other_calls,
            "pending_outcome": None,
        }
        if outcome_calls:
            args = outcome_calls[-1].arguments
            update["pending_outcome"] = {"call_id": outcome_calls[-1].id, "arguments": args}
        elif not other_calls:
            messages.append({"role": "user", "content": NUDGE})
        update["messages"] = messages
        return update

    def act(state: AgentState) -> dict[str, Any]:
        observations = list(state["observations"])
        messages = list(state["messages"])
        for call in state["pending_calls"]:
            external = hooks.should_stop()
            if external is not None:
                hooks.on_event("limit_exceeded", "act", {"reason": external})
                return {
                    "observations": observations,
                    "messages": messages,
                    "pending_calls": [],
                    "pending_outcome": None,
                    "stop_reason": external,
                }
            outcome = gateway.call(call["name"], call["arguments"])
            body = outcome.model_dump(mode="json")
            observations.append(
                Observation(
                    seq=gateway.calls[-1].seq,
                    call_id=call["id"],
                    tool=call["name"],
                    arguments=call["arguments"],
                    ok=outcome.ok,
                    data=body.get("data") if outcome.ok else None,
                    error=None if outcome.ok else body,
                    evidence_ids=list(body.get("evidence_ids", [])),
                )
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": call["name"],
                    "content": json.dumps(body, ensure_ascii=False),
                }
            )
        return {"observations": observations, "messages": messages, "pending_calls": []}

    def finalize(state: AgentState) -> dict[str, Any]:
        if state["stop_reason"] is not None:
            return {}
        pending = state["pending_outcome"] or {}
        try:
            outcome = AgentOutcome.model_validate(pending.get("arguments"))
        except ValidationError as exc:
            problems = [
                f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}"
                for e in exc.errors()
            ]
            error = {"stage": "finalize", "type": "invalid_outcome", "problems": problems}
            final_attempt = state["repair_attempts"] >= MAX_REPAIR_ATTEMPTS
            hooks.on_event(
                "outcome_invalid",
                "finalize",
                {
                    "problems": problems,
                    "arguments": pending.get("arguments"),
                    "final": final_attempt,
                },
            )
            if final_attempt:
                return {"stop_reason": "malformed_output", "errors": [*state["errors"], error]}
            repair = {
                "role": "tool",
                "tool_call_id": pending.get("call_id", SUBMIT_OUTCOME),
                "name": SUBMIT_OUTCOME,
                "content": json.dumps(
                    {"ok": False, "code": "invalid_outcome", "problems": problems}
                ),
            }
            return {
                "repair_attempts": state["repair_attempts"] + 1,
                "pending_outcome": None,
                "messages": [*state["messages"], repair],
                "errors": [*state["errors"], error],
            }
        submitted = outcome.model_dump(mode="json")
        hooks.on_event("outcome_submitted", "finalize", submitted)
        return {"outcome": submitted, "stop_reason": "completed"}

    def after_decide(state: AgentState) -> str:
        if state["stop_reason"] is not None:
            return "finalize"
        if state["pending_calls"]:
            return "act"
        if state["pending_outcome"] is not None:
            return "finalize"
        return "decide"

    def after_act(state: AgentState) -> str:
        if state["stop_reason"] is not None or state["pending_outcome"] is not None:
            return "finalize"
        return "decide"

    def after_finalize(state: AgentState) -> str:
        return END if state["stop_reason"] is not None else "decide"

    graph = StateGraph(AgentState)
    graph.add_node("intake", intake)
    graph.add_node("decide", decide)
    graph.add_node("act", act)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "decide")
    graph.add_conditional_edges("decide", after_decide, ["act", "finalize", "decide"])
    graph.add_conditional_edges("act", after_act, ["finalize", "decide"])
    graph.add_conditional_edges("finalize", after_finalize, ["decide", END])
    return graph.compile()


def run_agent(
    agent_input: AgentInput,
    decider: Decider,
    gateway: ToolGateway,
    *,
    system_prompt: str,
    limits: AgentLimits | None = None,
    hooks: RunHooks | None = None,
) -> AgentRunResult:
    limits = limits or AgentLimits()
    started = time.monotonic()
    usage_log: list[dict[str, Any]] = []
    graph = build_agent_graph(
        decider,
        gateway,
        system_prompt=system_prompt,
        limits=limits,
        deadline=started + limits.timeout_s,
        usage_log=usage_log,
        hooks=hooks,
    )
    initial: AgentState = {
        "input": agent_input.model_dump(mode="json"),
        "messages": [],
        "observations": [],
        "pending_calls": [],
        "pending_outcome": None,
        "outcome": None,
        "step_count": 0,
        "repair_attempts": 0,
        "stop_reason": None,
        "errors": [],
        "deadline": started + limits.timeout_s,
    }
    # A step visits at most decide -> act -> finalize; the margin covers repairs and nudges.
    final = graph.invoke(initial, config={"recursion_limit": limits.max_steps * 4 + 10})
    outcome = AgentOutcome.model_validate(final["outcome"]) if final["outcome"] else None
    return AgentRunResult(
        outcome=outcome,
        stop_reason=final["stop_reason"] or "agent_error",
        steps=final["step_count"],
        tool_calls=list(gateway.calls),
        actions=list(gateway.actions.actions),
        messages=final["messages"],
        errors=final["errors"],
        duration_ms=round((time.monotonic() - started) * 1000),
        usage=usage_log,
    )
