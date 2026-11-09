"""Contracts between the platform and the agent under test.

- `AgentInput` is everything the agent is told up front (decision D-04: no ground truth, and
  nothing that hints at it, such as the scenario ID, title, category or tags).
- `AgentOutcome` is the structured answer the agent submits via the `submit_outcome` tool
  (PROJECT.md §7.3, decision D-12).
- `ModelTurn` / `ToolCallRequest` are provider-neutral shapes for LLM turns (Phase 6).
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.taxonomy import RootCause

SUBMIT_OUTCOME = "submit_outcome"


class AgentOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    root_cause: RootCause | None = Field(
        description="One label from root_cause_labels; insufficient_evidence if unsupported"
    )
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_ids: list[str] = Field(
        default_factory=list, description="evidence_id values returned by tools that support it"
    )
    action_summary: list[str] = Field(default_factory=list, description="Actions you took")
    escalation: bool = Field(description="True if you escalated the case")
    customer_response: str = Field(min_length=1, max_length=2000)
    uncertainty_note: str | None = Field(default=None, max_length=1000)


class RootCauseLabel(BaseModel):
    label: str
    description: str


class AgentInput(BaseModel):
    customer_message: str
    visible_context: dict[str, str]
    now: str = Field(description="Current date and time (ISO 8601) for this case")
    root_cause_labels: list[RootCauseLabel]
    tools: list[dict[str, Any]]


class ToolCallRequest(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] | Any = Field(default_factory=dict)


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None


class ModelTurn(BaseModel):
    """One model response with thought/reasoning parts already removed (decision D-11)."""

    text: str | None = None
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    usage: Usage | None = None
    model_id: str | None = None


StopReason = Literal[
    "completed",  # a valid outcome was submitted
    "step_limit",  # max_steps reached without an outcome
    "timeout",  # wall-clock deadline passed
    "malformed_output",  # outcome still invalid after the repair attempt
    "agent_error",  # the decider raised
]
