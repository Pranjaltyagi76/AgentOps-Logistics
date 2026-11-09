"""Builds the agent's input. This is the ONLY place agent input is assembled (decision D-04).

Deliberately excluded, because they reveal or hint at the answer: ground truth, evaluation
rules, rubric, author note, fault injection, mock data (reachable only through tools), and
the scenario ID, title, description, category, difficulty and tags.
"""

from typing import Any

from app.domain.taxonomy import ROOT_CAUSE_INFO
from app.schemas.scenario import ScenarioSpec
from app.services.agent_graph.schemas import (
    SUBMIT_OUTCOME,
    AgentInput,
    AgentOutcome,
    RootCauseLabel,
)
from app.services.tools.registry import tool_specs


def submit_outcome_spec() -> dict[str, Any]:
    schema = AgentOutcome.model_json_schema()
    schema.pop("title", None)
    return {
        "name": SUBMIT_OUTCOME,
        "description": (
            "Finish the case: submit your structured outcome and the reply to the customer. "
            "Call this exactly once, after you have gathered the evidence you need."
        ),
        "parameters": schema,
    }


def build_agent_input(spec: ScenarioSpec, permitted_tools: frozenset[str]) -> AgentInput:
    return AgentInput(
        customer_message=spec.customer_message,
        visible_context=dict(spec.visible_context),
        now=spec.as_of.isoformat(),
        root_cause_labels=[
            RootCauseLabel(label=label.value, description=info.description)
            for label, info in ROOT_CAUSE_INFO.items()
        ],
        tools=[*tool_specs(permitted_tools), submit_outcome_spec()],
    )
