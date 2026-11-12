"""Runs one agent config against one scenario: decider + gateway + graph.

Phase 4's run executor calls `run_scenario` inside a background job and plugs a trace
collector in as the gateway observer. LLM configs get an `LLMDecider` over the provider built
by `services/providers/factory.py` (Phase 6).
"""

import time
from collections.abc import Callable
from typing import cast

from app.core.config import Settings, get_settings
from app.schemas.agent_config import AgentConfigSpec
from app.schemas.scenario import ScenarioSpec
from app.services.agent_graph.agent_input import build_agent_input
from app.services.agent_graph.deciders import Decider, LLMDecider
from app.services.agent_graph.graph import AgentLimits, AgentRunResult, RunHooks, run_agent
from app.services.agent_graph.rule_based import Profile, RuleBasedDecider
from app.services.providers.factory import build_provider
from app.services.sops.service import SopSearcher
from app.services.tools.data_view import ScenarioDataView
from app.services.tools.gateway import ToolGateway, ToolObserver


def build_decider(
    config: AgentConfigSpec,
    settings: Settings | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] = lambda: False,
    on_pause: Callable[[float], None] = lambda seconds: None,
) -> Decider:
    """Rule-based profile, or an LLMDecider over the configured provider.

    Raises ProviderNotConfiguredError when the provider has no API key on this server.
    """
    if config.provider == "rule_based":
        return RuleBasedDecider(cast(Profile, config.model_id))
    provider = build_provider(
        config,
        settings or get_settings(),
        sleep=sleep,
        should_stop=should_stop,
        on_pause=on_pause,
    )
    return LLMDecider(provider, temperature=config.temperature)


def run_scenario(
    scenario: ScenarioSpec,
    config: AgentConfigSpec,
    sops: SopSearcher,
    *,
    observer: ToolObserver | None = None,
    sleep: Callable[[float], None] | None = None,
    decider: Decider | None = None,
    hooks: RunHooks | None = None,
    settings: Settings | None = None,
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
        decider
        or build_decider(
            config,
            settings,
            sleep=sleep or time.sleep,
            should_stop=lambda: hooks is not None and hooks.should_stop() is not None,
            on_pause=hooks.on_pause if hooks is not None else (lambda seconds: None),
        ),
        gateway,
        system_prompt=config.system_prompt or "",
        limits=AgentLimits(max_steps=config.max_steps, timeout_s=config.timeout_s),
        hooks=hooks,
    )
