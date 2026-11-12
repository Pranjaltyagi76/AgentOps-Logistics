"""GeminiProvider against a scripted fake client: request building, thought stripping,
thought-signature replay, retries, error mapping and the request throttle. No network."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from google.genai import types
from pydantic import SecretStr

from app.core.config import Settings
from app.schemas.agent_config import AgentConfigSpec
from app.schemas.scenario import ScenarioSpec
from app.services.agent_graph.agent_input import build_agent_input
from app.services.agent_graph.deciders import LLMDecider
from app.services.agent_graph.graph import AgentLimits, RunHooks, run_agent
from app.services.providers import factory
from app.services.providers.errors import (
    ProviderAuthError,
    ProviderBadRequestError,
    ProviderNotConfiguredError,
    ProviderQuotaError,
    ProviderUnavailableError,
)
from app.services.providers.gemini import (
    GeminiProvider,
    inline_refs,
    parse_response,
    thinking_config,
    to_contents,
    to_function_declarations,
)
from app.services.providers.throttle import RequestThrottle
from app.services.tools.data_view import ScenarioDataView
from app.services.tools.gateway import ToolGateway
from tests.gemini_fakes import (
    SIGNATURE,
    THOUGHT_TEXT,
    FakeGeminiClient,
    api_error,
    fcall,
    response,
    thought,
)

Factory = Callable[..., dict[str, Any]]

OUTCOME = {
    "root_cause": "hub_congestion",
    "evidence_ids": ["event:SHP-1042:05"],
    "escalation": False,
    "customer_response": "Your parcel is delayed by congestion at the Pune hub.",
}


class NoSops:
    def search(self, query: str, allowed: frozenset[str], top_k: int) -> list[Any]:
        return []


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def provider(script: list[Any], clock: Clock | None = None, **kwargs: Any) -> GeminiProvider:
    clock = clock or Clock()
    return GeminiProvider(
        FakeGeminiClient(script),
        "gemini-3.5-flash",
        throttle=kwargs.pop("throttle", RequestThrottle(1000, clock=clock)),
        sleep=clock.sleep,
        clock=clock,
        **kwargs,
    )


def run_with(
    spec_data: dict[str, Any], gemini: GeminiProvider, hooks: RunHooks | None = None
) -> Any:
    spec = ScenarioSpec.model_validate(spec_data)
    gateway = ToolGateway.for_scenario(
        ScenarioDataView.from_spec(spec), NoSops(), sleep=lambda s: None
    )
    return run_agent(
        build_agent_input(spec, gateway.permitted_tools),
        LLMDecider(gemini),
        gateway,
        system_prompt="You are a test agent.",
        limits=AgentLimits(max_steps=6),
        hooks=hooks,
    )


# --- request building --------------------------------------------------------------------


def test_tool_schemas_are_inlined_without_refs(make_scenario: Factory) -> None:
    spec = ScenarioSpec.model_validate(make_scenario())
    tools = build_agent_input(spec, frozenset(spec.available_tools)).tools
    declarations = to_function_declarations(tools)
    assert [d.name for d in declarations] == [t["name"] for t in tools]
    for declaration in declarations:
        text = json.dumps(declaration.parameters_json_schema)
        assert "$ref" not in text and "$defs" not in text
    outcome = next(d for d in declarations if d.name == "submit_outcome")
    root_cause = json.dumps(outcome.parameters_json_schema["properties"]["root_cause"])
    assert "hub_congestion" in root_cause and "insufficient_evidence" in root_cause


def test_inline_refs_keeps_sibling_keys() -> None:
    schema = {
        "type": "object",
        "properties": {"color": {"$ref": "#/$defs/Color", "description": "pick one"}},
        "$defs": {"Color": {"type": "string", "enum": ["red", "blue"]}},
    }
    assert inline_refs(schema) == {
        "type": "object",
        "properties": {
            "color": {"type": "string", "enum": ["red", "blue"], "description": "pick one"}
        },
    }


def test_messages_become_contents_with_grouped_tool_responses() -> None:
    messages = [
        {"role": "system", "content": "be good"},
        {"role": "user", "content": '{"customer_message": "hi"}'},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "a", "name": "get_shipment", "arguments": {"shipment_id": "S1"}},
                {"id": "b", "name": "get_ticket", "arguments": {"ticket_id": "T1"}},
            ],
        },
        {"role": "tool", "tool_call_id": "a", "name": "get_shipment", "content": '{"ok": true}'},
        {"role": "tool", "tool_call_id": "b", "name": "get_ticket", "content": '{"ok": false}'},
        {"role": "user", "content": "nudge"},
    ]
    system, contents = to_contents(messages, [], set())
    assert system == "be good"
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert [p.function_call.name for p in contents[1].parts] == ["get_shipment", "get_ticket"]
    last = contents[2].parts
    assert [p.function_response.response for p in last[:2]] == [{"ok": True}, {"ok": False}]
    assert last[2].text == "nudge"


def test_unanswered_function_calls_get_a_placeholder_response() -> None:
    messages = [
        {"role": "user", "content": "case"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "a", "name": "submit_outcome", "arguments": {}},
                {"id": "b", "name": "submit_outcome", "arguments": {}},
            ],
        },
        {"role": "tool", "tool_call_id": "b", "name": "submit_outcome", "content": "{}"},
    ]
    _, contents = to_contents(messages, [], set())
    responses = [p.function_response for p in contents[2].parts]
    assert [r.name for r in responses] == ["submit_outcome", "submit_outcome"]
    assert responses[0].response["code"] == "not_executed"


def test_thinking_is_minimised_and_never_requested_as_text() -> None:
    new = thinking_config("gemini-3.5-flash", "minimal")
    assert new.thinking_level == types.ThinkingLevel.MINIMAL and new.include_thoughts is False
    old = thinking_config("gemini-2.5-flash", "minimal")
    assert old.thinking_budget == 0 and old.include_thoughts is False

    gemini = provider([response(fcall("submit_outcome", OUTCOME))])
    gemini.generate([{"role": "user", "content": "x"}], [], temperature=1.0)
    config = gemini.client.models.requests[0]["config"]
    assert config.thinking_config.include_thoughts is False
    assert config.automatic_function_calling.disable is True
    assert config.tool_config.function_calling_config.mode == types.FunctionCallingConfigMode.ANY


# --- thought parts and signatures -----------------------------------------------------------


def test_thought_parts_are_dropped_from_the_turn() -> None:
    reply = response(
        thought(), types.Part(text="Checking."), fcall("get_shipment", {"shipment_id": "S"})
    )
    turn, replay, _ = parse_response(reply, 1, "gemini-x")
    assert turn.text == "Checking."
    assert [c.name for c in turn.tool_calls] == ["get_shipment"]
    assert THOUGHT_TEXT not in turn.model_dump_json()
    assert all(not p.thought and p.text != THOUGHT_TEXT for p in replay)
    assert turn.usage is not None and turn.usage.thinking_tokens == 7
    assert turn.model_id == "gemini-3.5-flash"


def test_full_run_keeps_thoughts_out_and_replays_signatures(make_scenario: Factory) -> None:
    gemini = provider(
        [
            response(
                thought(), fcall("get_tracking_events", {"shipment_id": "SHP-1042"}, signed=True)
            ),
            response(thought(), fcall("submit_outcome", OUTCOME, signed=True)),
        ]
    )
    events: list[tuple[str, dict[str, Any]]] = []
    hooks = RunHooks(on_event=lambda kind, node, payload: events.append((kind, payload)))
    result = run_with(make_scenario(), gemini, hooks)

    assert result.stop_reason == "completed"
    assert result.outcome is not None and result.outcome.root_cause == "hub_congestion"
    persisted = json.dumps([result.messages, events, result.usage, result.errors], default=str)
    assert THOUGHT_TEXT not in persisted
    assert "signature" not in persisted and SIGNATURE.decode() not in persisted
    # ...but Gemini got its signature back with the second request.
    second = gemini.client.models.requests[1]["contents"]
    model_turn = next(c for c in second if c.role == "model")
    assert model_turn.parts[0].thought_signature == SIGNATURE
    assert all(not p.thought for c in second for p in c.parts or [])
    assert result.usage[0] == {"input_tokens": 100, "output_tokens": 20, "thinking_tokens": 7}


# --- retries and errors ---------------------------------------------------------------------


def test_transient_errors_are_retried_with_backoff() -> None:
    clock = Clock()
    gemini = provider(
        [api_error(503, "UNAVAILABLE"), api_error(500, "INTERNAL"), response(fcall("x"))], clock
    )
    turn = gemini.generate([{"role": "user", "content": "x"}], [], temperature=1.0)
    assert [c.name for c in turn.tool_calls] == ["x"]
    assert clock.sleeps == [1.0, 4.0]
    assert gemini.request_count == 3


def test_quota_errors_end_as_provider_quota_after_retries() -> None:
    clock = Clock()
    gemini = provider([api_error(429, "RESOURCE_EXHAUSTED", retry_s=6)], clock)
    with pytest.raises(ProviderQuotaError) as info:
        gemini.generate([{"role": "user", "content": "x"}], [], temperature=1.0)
    assert info.value.status == 429
    assert clock.sleeps == [6.0, 6.0]  # the server's retry hint beats a shorter backoff


def test_long_retry_hints_and_deadlines_stop_retrying_early() -> None:
    clock = Clock()
    gemini = provider([api_error(429, "RESOURCE_EXHAUSTED", retry_s=45)], clock)
    with pytest.raises(ProviderQuotaError):
        gemini.generate([{"role": "user", "content": "x"}], [], temperature=1.0)
    assert clock.sleeps == [] and gemini.request_count == 1

    clock = Clock()
    gemini = provider([api_error(503, "UNAVAILABLE")], clock)
    with pytest.raises(ProviderUnavailableError):
        gemini.generate(
            [{"role": "user", "content": "x"}], [], temperature=1.0, deadline=clock.now + 0.5
        )
    assert clock.sleeps == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            api_error(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key."),
            ProviderAuthError,
        ),
        (api_error(403, "PERMISSION_DENIED"), ProviderAuthError),
        (api_error(404, "NOT_FOUND", "model not found"), ProviderBadRequestError),
        (
            api_error(400, "INVALID_ARGUMENT", "Thinking level MINIMAL is not supported"),
            ProviderBadRequestError,
        ),
        (httpx.ReadTimeout("timed out"), ProviderUnavailableError),
        (httpx.ConnectError("refused"), ProviderUnavailableError),
    ],
)
def test_errors_are_mapped_to_typed_provider_errors(
    error: BaseException, expected: type[Exception]
) -> None:
    gemini = provider([error], max_retries=0)
    with pytest.raises(expected):
        gemini.generate([{"role": "user", "content": "x"}], [], temperature=1.0)


def test_non_retryable_errors_are_not_retried() -> None:
    clock = Clock()
    gemini = provider([api_error(400, "INVALID_ARGUMENT", "bad schema")], clock)
    with pytest.raises(ProviderBadRequestError):
        gemini.generate([{"role": "user", "content": "x"}], [], temperature=1.0)
    assert gemini.request_count == 1 and clock.sleeps == []


def test_provider_failure_stops_the_graph_as_a_platform_error(make_scenario: Factory) -> None:
    gemini = provider([api_error(429, "RESOURCE_EXHAUSTED")], max_retries=0)
    result = run_with(make_scenario(), gemini)
    assert result.stop_reason == "provider_error"
    assert result.outcome is None
    assert result.errors[-1]["code"] == "provider_quota"
    assert result.errors[-1]["type"] == "ProviderQuotaError"


def test_a_cancel_during_provider_wait_is_reported_as_cancelled(make_scenario: Factory) -> None:
    stop = {"reason": None}

    def sleep_then_cancel(seconds: float) -> None:
        stop["reason"] = "cancelled"

    gemini = GeminiProvider(
        FakeGeminiClient([api_error(503, "UNAVAILABLE")]),
        "gemini-3.5-flash",
        throttle=RequestThrottle(1000),
        sleep=sleep_then_cancel,
        should_stop=lambda: stop["reason"] is not None,
    )
    hooks = RunHooks(should_stop=lambda: stop["reason"])
    result = run_with(make_scenario(), gemini, hooks)
    assert result.stop_reason == "cancelled"
    assert gemini.request_count == 1


# --- throttle -------------------------------------------------------------------------------


def test_throttle_waits_for_a_free_slot_in_the_window() -> None:
    clock = Clock()
    throttle = RequestThrottle(2, clock=clock)
    throttle.acquire(sleep=clock.sleep)
    clock.now += 10
    throttle.acquire(sleep=clock.sleep)
    throttle.acquire(sleep=clock.sleep)  # third in the same minute: waits for the first slot
    assert clock.sleeps == [50.0]
    assert throttle.used() == 2


def test_throttle_refuses_to_wait_past_the_deadline() -> None:
    clock = Clock()
    throttle = RequestThrottle(1, clock=clock)
    throttle.acquire(sleep=clock.sleep)
    with pytest.raises(ProviderQuotaError):
        throttle.acquire(sleep=clock.sleep, deadline=clock.now + 30)
    assert clock.sleeps == []


# --- factory and config ---------------------------------------------------------------------


def gemini_config(**overrides: Any) -> AgentConfigSpec:
    return AgentConfigSpec.model_validate(
        {"name": "gemini-test", "provider": "gemini", "model_id": "default", **overrides}
    )


def test_factory_needs_a_key_and_resolves_the_default_model(test_settings: Settings) -> None:
    with pytest.raises(ProviderNotConfiguredError):
        factory.build_provider(gemini_config(), test_settings)
    assert factory.resolve_model_id(gemini_config(), test_settings) == test_settings.gemini_model
    assert factory.resolve_model_id(gemini_config(model_id="gemini-3.8-flash"), test_settings) == (
        "gemini-3.8-flash"
    )

    keyed = test_settings.model_copy(update={"gemini_api_key": SecretStr("test-key")})
    built = factory.build_provider(gemini_config(max_retries=1), keyed, client=object())
    assert built.model_id == keyed.gemini_model and built.max_retries == 1
    assert built.throttle is factory.gemini_throttle(keyed.gemini_rpm_limit)


def test_openai_configs_are_not_runnable(test_settings: Settings) -> None:
    config = AgentConfigSpec.model_validate(
        {"name": "openai-test", "provider": "openai", "model_id": "gpt-x"}
    )
    assert factory.provider_problem(config, test_settings) is not None


@pytest.mark.parametrize("model_id", ["gpt-4o", "gemini", "Gemini-3.5-flash", "defaults"])
def test_gemini_model_ids_are_validated(model_id: str) -> None:
    with pytest.raises(ValueError, match="gemini model_id"):
        gemini_config(model_id=model_id)


def test_blank_keys_in_env_mean_not_configured() -> None:
    settings = Settings(_env_file=None, gemini_api_key="  ")  # type: ignore[call-arg]
    assert settings.gemini_api_key is None


def test_request_timeout_never_drops_below_geminis_minimum() -> None:
    clock = Clock()
    gemini = provider([response(fcall("x"))], clock, request_timeout_s=20.0)
    gemini.generate([{"role": "user", "content": "x"}], [], temperature=1.0, deadline=clock.now + 3)
    assert gemini.client.models.requests[0]["config"].http_options.timeout == 10_000

    gemini.generate(
        [{"role": "user", "content": "x"}], [], temperature=1.0, deadline=clock.now + 60
    )
    assert gemini.client.models.requests[1]["config"].http_options.timeout == 20_000


def test_no_retry_when_a_retry_could_not_finish_before_the_deadline() -> None:
    clock = Clock()
    gemini = provider([api_error(503, "UNAVAILABLE")], clock)
    with pytest.raises(ProviderUnavailableError):
        gemini.generate(
            [{"role": "user", "content": "x"}], [], temperature=1.0, deadline=clock.now + 8
        )
    assert gemini.request_count == 1 and clock.sleeps == []
