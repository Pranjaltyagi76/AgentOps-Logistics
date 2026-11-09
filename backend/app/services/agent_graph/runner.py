"""Runs one agent config against one scenario: decider + gateway + graph.

Phase 4's run executor calls `run_scenario` inside a background job and plugs a trace
collector in as the gateway observer.
"""

from collections.abc import Callable
from typing import cast

from app.schemas.agent_config import AgentConfigSpec
from app.schemas.scenario import ScenarioSpec
from app.services.agent_graph.agent_input import build_agent_input
from app.services.agent_graph.deciders import Decider
from app.services.agent_graph.graph import AgentLimits, AgentRunResult, run_agent
from app.services.agent_graph.rule_based import Profile, RuleBasedDecider
from app.services.sops.service import SopSearcher
from app.services.tools.data_view import ScenarioDataView
from app.services.tools.gateway import ToolGateway, ToolObserver


class ProviderNotConfiguredError(RuntimeError):
    """The config needs an LLM provider that is not set up on this server (Phase 6)."""


def build_decider(config: AgentConfigSpec) -> Decider:
    if config.provider == "rule_based":
        return RuleBasedDecider(cast(Profile, config.model_id))
    raise ProviderNotConfiguredError(
        f"Provider '{config.provider}' is not available yet (LLM agents arrive in Phase 6)"
    )


def run_scenario(
    scenario: ScenarioSpec,
    config: AgentConfigSpec,
    sops: SopSearcher,
    *,
    observer: ToolObserver | None = None,
    sleep: Callable[[float], None] | None = None,
    decider: Decider | None = None,
) -> AgentRunResult:
    gateway = ToolGateway.for_scenario(
        ScenarioDataView.from_spec(scenario),
        sops,
        agent_tools=frozenset(config.tools),
        max_tool_calls=config.max_tool_calls,
        observer=observer,
        **({"sleep": sleep} if sleep is not None else {}),
    )
    return run_agent(
        build_agent_input(scenario, gateway.permitted_tools),
        decider or build_decider(config),
        gateway,
        system_prompt=config.system_prompt or "",
        limits=AgentLimits(max_steps=config.max_steps, timeout_s=config.timeout_s),
    )
