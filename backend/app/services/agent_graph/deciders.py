"""Deciders choose the agent's next move in the graph's `decide` node.

- `LLMDecider` asks a `ModelProvider` (Gemini in Phase 6; `FakeProvider` in tests).
- `RuleBasedDecider` (rule_based.py) uses deterministic heuristics, no LLM.

Both see the same `AgentState`: the agent input, the visible message history and the tool
observations. Neither can see ground truth.
"""

from collections.abc import Iterable
from typing import Any, Protocol, TypedDict

from app.services.agent_graph.schemas import ModelTurn, ToolCallRequest


class Observation(TypedDict):
    seq: int
    call_id: str
    tool: str
    arguments: Any
    ok: bool
    data: Any  # ToolResult.data when ok
    error: dict[str, Any] | None  # ToolError fields when not ok
    evidence_ids: list[str]


class AgentState(TypedDict):
    input: dict[str, Any]  # AgentInput.model_dump()
    messages: list[dict[str, Any]]
    observations: list[Observation]
    pending_calls: list[dict[str, Any]]
    pending_outcome: dict[str, Any] | None
    outcome: dict[str, Any] | None
    step_count: int
    repair_attempts: int
    stop_reason: str | None
    errors: list[dict[str, Any]]


class Decider(Protocol):
    name: str

    def decide(self, state: AgentState) -> ModelTurn: ...


class ModelProvider(Protocol):
    name: str

    def generate(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, temperature: float
    ) -> ModelTurn: ...


class LLMDecider:
    """Wraps a ModelProvider: sends the visible conversation and tool specs, returns its turn."""

    def __init__(self, provider: ModelProvider, *, temperature: float = 0.0) -> None:
        self.provider = provider
        self.temperature = temperature
        self.name = f"llm:{provider.name}"

    def decide(self, state: AgentState) -> ModelTurn:
        return self.provider.generate(
            state["messages"], state["input"]["tools"], temperature=self.temperature
        )


class FakeProvider:
    """Replays scripted turns, for graph tests. Repeats the last turn when the script runs out."""

    name = "fake"

    def __init__(self, turns: Iterable[ModelTurn]) -> None:
        self.turns = list(turns)
        self.calls = 0

    def generate(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, temperature: float
    ) -> ModelTurn:
        turn = self.turns[min(self.calls, len(self.turns) - 1)]
        self.calls += 1
        return turn


def call(
    name: str, arguments: dict[str, Any] | None = None, call_id: str | None = None
) -> ToolCallRequest:
    """Shorthand for building tool-call requests (used by deciders and tests)."""
    return ToolCallRequest(id=call_id or name, name=name, arguments=arguments or {})
