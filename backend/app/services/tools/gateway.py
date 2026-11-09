"""The only way an agent can act: every tool call goes through `ToolGateway.call`.

Pipeline (context/architecture.md §5):
    1. known tool?                    else unknown_tool
    2. permitted for this run?        else tool_not_permitted
    3. tool-call budget left?         else tool_budget_exceeded
    4. arguments valid (Pydantic)?    else invalid_arguments
    5. policy allows it?              else policy_denied
    6. scenario fault injection       (simulated latency, timeout / malformed / unavailable)
    7. handler -> ToolResult with evidence IDs

Every call, including rejected ones, is recorded as a `ToolCallRecord` and passed to the
observer, which becomes the trace collector in Phase 4.
"""

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol

from pydantic import ValidationError

from app.domain.policy import POLICY_VERSION, PolicyEngine
from app.schemas.scenario import FaultInjection
from app.services.sops.service import SopSearcher
from app.services.tools.data_view import ScenarioDataView
from app.services.tools.handlers import ActionLog, HandlerContext
from app.services.tools.registry import REGISTRY, TOOL_REGISTRY_VERSION
from app.services.tools.schemas import ToolError, ToolOutcome

DEFAULT_MAX_TOOL_CALLS = 10

_FAULT_MESSAGES = {
    "timeout": ("The upstream system did not respond in time.", True),
    "malformed_response": (
        "The upstream system returned a response that could not be read.",
        False,
    ),
    "unavailable": ("The upstream system is temporarily unavailable.", True),
}


@dataclass(frozen=True)
class ToolCallRecord:
    seq: int
    tool: str
    arguments: dict[str, Any]
    outcome: ToolOutcome
    duration_ms: int
    simulated_latency_ms: int = 0
    policy_rule_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome.ok


class ToolObserver(Protocol):
    def on_tool_call(self, record: ToolCallRecord) -> None: ...


@dataclass
class ToolGateway:
    data: ScenarioDataView
    sops: SopSearcher
    permitted_tools: frozenset[str]
    policy: PolicyEngine = field(default_factory=PolicyEngine)
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS
    observer: ToolObserver | None = None
    # Injectable so tests don't really wait for simulated latency.
    sleep: Callable[[float], None] = time.sleep
    actions: ActionLog = field(default_factory=ActionLog)
    calls: list[ToolCallRecord] = field(default_factory=list)
    _executions: Counter[str] = field(default_factory=Counter)

    # Recorded with every run for reproducibility (NFR-08).
    versions: ClassVar[dict[str, str]] = {
        "tool_registry": TOOL_REGISTRY_VERSION,
        "policy": POLICY_VERSION,
    }

    @classmethod
    def for_scenario(
        cls,
        data: ScenarioDataView,
        sops: SopSearcher,
        *,
        agent_tools: frozenset[str] | None = None,
        **kwargs: Any,
    ) -> "ToolGateway":
        """Permitted tools = the scenario's available tools ∩ the agent config's tool set."""
        permitted = (
            data.available_tools if agent_tools is None else data.available_tools & agent_tools
        )
        return cls(data=data, sops=sops, permitted_tools=frozenset(permitted), **kwargs)

    @property
    def budget_remaining(self) -> int:
        return max(0, self.max_tool_calls - len(self.calls))

    def call(self, tool: str, arguments: dict[str, Any] | None) -> ToolOutcome:
        started = time.perf_counter()
        raw_args = arguments if isinstance(arguments, dict) else {}
        outcome, latency_ms, rule_id = self._run(tool, raw_args, arguments)
        record = ToolCallRecord(
            seq=len(self.calls) + 1,
            tool=tool,
            arguments=raw_args,
            outcome=outcome,
            duration_ms=round((time.perf_counter() - started) * 1000),
            simulated_latency_ms=latency_ms,
            policy_rule_id=rule_id,
        )
        self.calls.append(record)
        if self.observer is not None:
            self.observer.on_tool_call(record)
        return outcome

    def _run(
        self, tool: str, raw_args: dict[str, Any], original: object
    ) -> tuple[ToolOutcome, int, str | None]:
        definition = REGISTRY.get(tool)
        if definition is None:
            return self._error(tool, "unknown_tool", f"There is no tool named '{tool}'."), 0, None
        if tool not in self.permitted_tools:
            return (
                self._error(tool, "tool_not_permitted", f"'{tool}' is not available in this run."),
                0,
                None,
            )
        if len(self.calls) >= self.max_tool_calls:
            message = f"Tool-call budget of {self.max_tool_calls} calls is used up."
            return self._error(tool, "tool_budget_exceeded", message), 0, None
        if not isinstance(original, dict):
            return (
                self._error(tool, "invalid_arguments", "Arguments must be a JSON object."),
                0,
                None,
            )

        try:
            args = definition.args_model.model_validate(raw_args)
        except ValidationError as exc:
            problems = [
                {"field": ".".join(str(p) for p in err["loc"]) or "(root)", "problem": err["msg"]}
                for err in exc.errors()
            ]
            return (
                self._error(
                    tool, "invalid_arguments", "Arguments failed validation.", {"errors": problems}
                ),
                0,
                None,
            )

        decision = self.policy.check(tool, args.model_dump(mode="json"))
        if not decision.allowed:
            error = self._error(
                tool,
                "policy_denied",
                decision.message or "Blocked by policy.",
                {"rule_id": decision.rule_id},
            )
            return error, 0, decision.rule_id

        self._executions[tool] += 1
        fault = self._fault_for(tool, self._executions[tool])
        latency_ms = fault.latency_ms if fault else 0
        if latency_ms:
            self.sleep(latency_ms / 1000)
        if fault is not None:
            message, retryable = _FAULT_MESSAGES[fault.error]
            return self._error(tool, fault.error, message, retryable=retryable), latency_ms, None

        context = HandlerContext(data=self.data, sops=self.sops, actions=self.actions)
        return definition.handler(context, args), latency_ms, None

    def _fault_for(self, tool: str, execution_number: int) -> FaultInjection | None:
        for fault in self.data.fault_injection:
            if fault.tool == tool and (fault.calls == "all" or execution_number in fault.calls):
                return fault
        return None

    @staticmethod
    def _error(
        tool: str,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        *,
        retryable: bool = False,
    ) -> ToolError:
        return ToolError(
            tool=tool, code=code, message=message, retryable=retryable, details=details or {}
        )  # type: ignore[arg-type]
