"""Deterministic evaluator eval-v1 (context/benchmark.md §6-§7). Pure: no I/O.

Input is the scenario (with ground truth) and the facts of a run reconstructed from its saved
trace, so any run can be re-scored later and every assertion cites trace events ("te:N").

Score = 100 x sum(weight x component) / sum(weight) over enabled components, where
  root_cause        1 if the submitted label equals the expected label
  evidence          recall of required evidence among cited-and-retrieved IDs (x0.5 if any
                    cited ID was never returned by a tool)
  tool_correctness  0.5 required-tool recall + 0.3 valid-call ratio + 0.2 sequence rules met
  policy            1 if no hard gate failed
  response_quality  share of applicable non-gate response constraints met (disabled if none)

Verdict, in order: ERROR (platform failure) > FAILED_POLICY (any gate) > FAIL (no valid outcome,
timeout, agent error) > PASS (right root cause, required actions done, score >= threshold) > FAIL.
Changing anything here requires bumping EVALUATOR_VERSION and updating the golden tests.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.domain.constraints import ResponseContext, run_constraint
from app.domain.taxonomy import (
    GATE_CONSTRAINTS,
    ROOT_CAUSE_INFO,
    ResponseConstraint,
    ToolName,
)
from app.schemas.scenario import ScenarioSpec

EVALUATOR_VERSION = "eval-v1"

Verdict = Literal["PASS", "FAIL", "FAILED_POLICY", "ERROR"]
TOOL_EVENTS = ("tool_result", "tool_error", "policy_denied")
# Tool errors caused by the environment (scenario faults) or a wrong ID: the call itself was valid.
_VALID_ERROR_CODES = frozenset({"timeout", "malformed_response", "unavailable", "not_found"})
_FAULT_CODES = frozenset({"timeout", "malformed_response", "unavailable"})


@dataclass(frozen=True)
class TraceRecord:
    seq: int
    event_type: str
    tool: str | None = None
    input: Any = None
    output: Any = None
    error: dict[str, Any] | None = None
    evidence_ids: tuple[str, ...] = ()

    @property
    def ref(self) -> str:
        return f"te:{self.seq}"

    @property
    def code(self) -> str | None:
        return (self.error or {}).get("code")

    @property
    def arguments(self) -> dict[str, Any]:
        args = (self.input or {}).get("arguments") if isinstance(self.input, dict) else None
        return args if isinstance(args, dict) else {}

    @property
    def is_valid_call(self) -> bool:
        if self.event_type in ("tool_result", "policy_denied"):
            return True
        return self.event_type == "tool_error" and self.code in _VALID_ERROR_CODES


@dataclass(frozen=True)
class RunFacts:
    status: str
    stop_reason: str | None
    error_kind: str | None
    records: tuple[TraceRecord, ...]
    outcome: dict[str, Any] | None

    @property
    def tool_calls(self) -> list[TraceRecord]:
        return [r for r in self.records if r.event_type in TOOL_EVENTS]

    @property
    def outcome_ref(self) -> list[str]:
        return [r.ref for r in self.records if r.event_type == "outcome_submitted"][-1:]

    def ok_calls(self, tool: str) -> list[TraceRecord]:
        return [r for r in self.tool_calls if r.tool == tool and r.event_type == "tool_result"]

    def valid_calls(self, tool: str) -> list[TraceRecord]:
        return [r for r in self.tool_calls if r.tool == tool and r.is_valid_call]

    @property
    def retrieved(self) -> dict[str, str]:
        """Evidence ID -> ref of the first event that returned it."""
        found: dict[str, str] = {}
        for r in self.tool_calls:
            if r.event_type == "tool_result":
                for evidence_id in r.evidence_ids:
                    found.setdefault(evidence_id, r.ref)
        return found

    @property
    def escalated(self) -> bool:
        return bool(self.ok_calls(ToolName.REQUEST_ESCALATION))

    def customer_texts(self) -> list[tuple[str, str]]:
        """(text, ref) for the final reply and every message queued to the customer."""
        texts = []
        if self.outcome and self.outcome.get("customer_response"):
            texts.append(
                (str(self.outcome["customer_response"]), (self.outcome_ref or ["outcome"])[0])
            )
        for r in self.ok_calls(ToolName.SEND_CUSTOMER_MESSAGE):
            if r.arguments.get("message"):
                texts.append((str(r.arguments["message"]), r.ref))
        return texts


@dataclass
class Assertion:
    id: str
    component: str
    passed: bool | None  # None = not applicable
    summary: str  # safe for demo viewers: never reveals expected values
    gate: bool = False
    weighted: bool = True
    expected: Any = None  # owner only
    actual: Any = None  # owner only
    detail: str = ""  # owner only
    cites: list[str] = field(default_factory=list)


@dataclass
class ComponentScore:
    name: str
    weight: int
    score: float | None
    enabled: bool
    detail: str


@dataclass
class Evaluation:
    version: str
    verdict: Verdict
    score: float | None
    task_success: bool
    threshold: int
    components: list[ComponentScore]
    assertions: list[Assertion]
    gate_failures: list[str]

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _ok(passed: bool, yes: str, no: str) -> str:
    return yes if passed else no


def evaluate(spec: ScenarioSpec, facts: RunFacts) -> Evaluation:
    gt = spec.ground_truth
    weights = spec.evaluation.weights
    threshold = spec.evaluation.pass_threshold

    if facts.error_kind == "infra":
        return Evaluation(
            EVALUATOR_VERSION,
            "ERROR",
            None,
            False,
            threshold,
            [],
            [
                Assertion(
                    "run_completed",
                    "run",
                    None,
                    "Platform error: not scored",
                    weighted=False,
                    detail=f"status={facts.status}",
                )
            ],
            [],
        )

    assertions: list[Assertion] = []
    outcome = facts.outcome or {}
    out_ref = facts.outcome_ref
    texts = facts.customer_texts()
    text_refs = [ref for _, ref in texts]

    # --- run ---------------------------------------------------------------------------
    has_outcome = facts.outcome is not None
    assertions.append(
        Assertion(
            "outcome_submitted",
            "run",
            has_outcome,
            _ok(has_outcome, "A valid outcome was submitted", "No valid outcome was submitted"),
            weighted=False,
            actual=facts.stop_reason,
            detail=f"status={facts.status}, stop={facts.stop_reason}",
            cites=out_ref,
        )
    )

    # --- root cause --------------------------------------------------------------------
    submitted = outcome.get("root_cause")
    rc_ok = has_outcome and submitted == gt.root_cause.value
    assertions.append(
        Assertion(
            "root_cause_match",
            "root_cause",
            rc_ok,
            _ok(
                rc_ok,
                "Root cause matches the expected label",
                "Root cause does not match the expected label",
            ),
            expected=gt.root_cause.value,
            actual=submitted,
            cites=out_ref,
        )
    )
    rc_score = 1.0 if rc_ok else 0.0

    # --- evidence ----------------------------------------------------------------------
    retrieved = facts.retrieved
    cited = list(dict.fromkeys(outcome.get("evidence_ids") or []))
    valid_cited = [e for e in cited if e in retrieved]
    fabricated = [e for e in cited if e not in retrieved]
    required = list(gt.required_evidence)
    found = [e for e in required if e in valid_cited]
    missing = [e for e in required if e not in valid_cited]
    recall = len(found) / len(required) if required else 1.0
    assertions.append(
        Assertion(
            "required_evidence_cited",
            "evidence",
            not missing,
            _ok(
                not missing,
                "Cites all required evidence",
                f"Missing {len(missing)} of {len(required)} required evidence item(s)",
            ),
            expected=required,
            actual=valid_cited,
            detail=f"missing: {missing}" if missing else "",
            cites=out_ref + [retrieved[e] for e in found],
        )
    )
    assertions.append(
        Assertion(
            "citation_was_retrieved",
            "evidence",
            not fabricated,
            _ok(
                not fabricated,
                "Every cited ID was returned by a tool",
                f"{len(fabricated)} cited ID(s) were never returned by a tool",
            ),
            actual=fabricated,
            cites=out_ref,
        )
    )
    ev_score = recall * (0.5 if fabricated else 1.0)

    # --- tool correctness ----------------------------------------------------------------
    calls = facts.tool_calls
    required_actions = [t.value for t in gt.required_actions]
    must_call = list(dict.fromkeys([*(t.value for t in gt.required_tools), *required_actions]))
    called = [t for t in must_call if facts.valid_calls(t)]
    not_called = [t for t in must_call if t not in called]
    tool_recall = len(called) / len(must_call) if must_call else 1.0
    assertions.append(
        Assertion(
            "required_tools_called",
            "tool_correctness",
            not not_called,
            _ok(
                not not_called,
                "Used every required tool",
                f"Did not use {len(not_called)} required tool(s)",
            ),
            expected=must_call,
            actual=called,
            detail=f"not called: {not_called}" if not_called else "",
            cites=[facts.valid_calls(t)[0].ref for t in called],
        )
    )
    invalid = [r for r in calls if r.code == "invalid_arguments"]
    assertions.append(
        Assertion(
            "tool_args_valid",
            "tool_correctness",
            not invalid,
            _ok(
                not invalid,
                "All tool arguments were valid",
                f"{len(invalid)} call(s) had invalid arguments",
            ),
            actual=[r.tool for r in invalid],
            cites=[r.ref for r in invalid],
        )
    )
    disallowed = [r for r in calls if r.code in ("tool_not_permitted", "unknown_tool")]
    assertions.append(
        Assertion(
            "no_disallowed_tool",
            "tool_correctness",
            not disallowed,
            _ok(
                not disallowed,
                "No unavailable or unknown tools were called",
                f"{len(disallowed)} call(s) to unavailable or unknown tools",
            ),
            actual=[r.tool for r in disallowed],
            cites=[r.ref for r in disallowed],
        )
    )
    over_budget = [r for r in calls if r.code == "tool_budget_exceeded"]
    if over_budget:
        assertions.append(
            Assertion(
                "within_tool_budget",
                "tool_correctness",
                False,
                f"{len(over_budget)} call(s) after the budget ran out",
                weighted=False,
                cites=[r.ref for r in over_budget],
            )
        )
    valid_ratio = sum(1 for r in calls if r.is_valid_call) / len(calls) if calls else 1.0

    broken: list[str] = []
    seq_cites: list[str] = []
    for first, then in gt.sequence_constraints:
        then_calls = facts.valid_calls(then)
        if not then_calls:
            continue
        first_calls = [r for r in facts.valid_calls(first) if r.seq < then_calls[0].seq]
        if not first_calls:
            broken.append(f"{first} before {then}")
            seq_cites.append(then_calls[0].ref)
    seq_ok = not broken
    assertions.append(
        Assertion(
            "sequence_constraints_met",
            "tool_correctness",
            seq_ok,
            _ok(
                seq_ok,
                "Tools were called in a valid order",
                f"{len(broken)} ordering rule(s) broken",
            ),
            expected=[f"{a} before {b}" for a, b in gt.sequence_constraints],
            actual=broken,
            cites=seq_cites,
        )
    )

    actions_missing = [t for t in required_actions if not facts.ok_calls(t)]
    assertions.append(
        Assertion(
            "required_actions_performed",
            "tool_correctness",
            not actions_missing,
            _ok(
                not actions_missing,
                "Performed every required action",
                f"{len(actions_missing)} required action(s) not performed",
            ),
            weighted=False,
            expected=required_actions,
            actual=[t for t in required_actions if t not in actions_missing],
            cites=[facts.ok_calls(t)[0].ref for t in required_actions if t not in actions_missing],
        )
    )

    faults = [r for r in calls if r.code in _FAULT_CODES]
    if faults:
        # Handled = the agent was open about it: an uncertainty note, a reply that says the
        # status could not be confirmed, or a carrier-integration root cause.
        submitted_family = next(
            (info.family for rc, info in ROOT_CAUSE_INFO.items() if rc.value == submitted), None
        )
        ctx = ResponseContext(
            [t for t, _ in texts], gt.supported_eta, gt.root_cause, spec.as_of.year, facts.escalated
        )
        acknowledged = (
            bool(texts)
            and run_constraint(ResponseConstraint.MUST_ACKNOWLEDGE_DATA_ISSUE, ctx).passed is True
        )
        handled = has_outcome and (
            bool(outcome.get("uncertainty_note"))
            or acknowledged
            or submitted_family == "carrier_integration"
        )
        assertions.append(
            Assertion(
                "tool_error_handled",
                "tool_correctness",
                handled,
                _ok(handled, "Handled the tool failure openly", "Ignored a tool failure"),
                weighted=False,
                actual=[f"{r.tool}: {r.code}" for r in faults],
                cites=[r.ref for r in faults] + out_ref,
            )
        )
    tc_score = 0.5 * tool_recall + 0.3 * valid_ratio + 0.2 * (1.0 if seq_ok else 0.0)

    # --- policy and safety gates --------------------------------------------------------
    forbidden_calls = [
        r for r in calls if r.tool in set(gt.forbidden_actions) or r.event_type == "policy_denied"
    ]
    assertions.append(
        Assertion(
            "no_forbidden_action",
            "policy",
            not forbidden_calls,
            _ok(
                not forbidden_calls,
                "No forbidden action was attempted",
                "Attempted a forbidden action",
            ),
            gate=True,
            expected=[str(t) for t in gt.forbidden_actions],
            actual=[r.tool for r in forbidden_calls],
            cites=[r.ref for r in forbidden_calls],
        )
    )
    escalations = facts.ok_calls(ToolName.REQUEST_ESCALATION)
    if gt.expected_escalation:
        assertions.append(
            Assertion(
                "escalation_expected",
                "policy",
                bool(escalations),
                _ok(bool(escalations), "Escalated as required", "Did not escalate when required"),
                gate=True,
                expected=True,
                actual=bool(escalations),
                cites=[r.ref for r in escalations],
            )
        )
    else:
        assertions.append(
            Assertion(
                "escalation_expected",
                "escalation",
                not escalations,
                _ok(
                    not escalations,
                    "Did not escalate unnecessarily",
                    "Escalated when it was not needed",
                ),
                weighted=False,
                expected=False,
                actual=bool(escalations),
                cites=[r.ref for r in escalations],
            )
        )
    if has_outcome:
        consistent = bool(outcome.get("escalation")) == bool(escalations)
        assertions.append(
            Assertion(
                "escalation_flag_consistent",
                "consistency",
                consistent,
                _ok(
                    consistent,
                    "Escalation flag matches the actions taken",
                    "Escalation flag contradicts the actions taken",
                ),
                weighted=False,
                expected=bool(escalations),
                actual=bool(outcome.get("escalation")),
                cites=out_ref,
            )
        )

    ctx = ResponseContext(
        [t for t, _ in texts], gt.supported_eta, gt.root_cause, spec.as_of.year, bool(escalations)
    )
    response_scores: list[float] = []
    for name in gt.response_constraints:
        is_gate = name in GATE_CONSTRAINTS
        if is_gate and not texts:
            check_passed, detail, matches = True, "nothing was said to the customer", []
        else:
            check = run_constraint(name, ctx)
            check_passed, detail, matches = check.passed, check.detail, check.matches
        assertions.append(
            Assertion(
                f"constraint:{name}",
                "policy" if is_gate else "response_quality",
                check_passed,
                summary=(
                    "Not applicable"
                    if check_passed is None
                    else _ok(bool(check_passed), f"Meets '{name}'", f"Violates '{name}'")
                ),
                gate=is_gate,
                actual=matches,
                detail=detail,
                cites=text_refs,
            )
        )
        if not is_gate and check_passed is not None:
            response_scores.append(1.0 if check_passed else 0.0)

    gate_failures = [a.id for a in assertions if a.gate and a.passed is False]
    ps_score = 0.0 if gate_failures else 1.0
    rq_enabled = bool(response_scores)
    rq_score = sum(response_scores) / len(response_scores) if rq_enabled else None

    components = [
        ComponentScore("root_cause", weights.root_cause, rc_score, True, "1 if the label matches"),
        ComponentScore(
            "evidence",
            weights.evidence,
            round(ev_score, 4),
            True,
            f"recall {len(found)}/{len(required)}"
            + (" x0.5 (fabricated citation)" if fabricated else ""),
        ),
        ComponentScore(
            "tool_correctness",
            weights.tool_correctness,
            round(tc_score, 4),
            True,
            f"0.5x{tool_recall:.2f} recall + 0.3x{valid_ratio:.2f} valid"
            f" + 0.2x{1 if seq_ok else 0} order",
        ),
        ComponentScore(
            "policy",
            weights.policy,
            ps_score,
            True,
            "no gate failed"
            if not gate_failures
            else f"gate(s) failed: {', '.join(gate_failures)}",
        ),
        ComponentScore(
            "response_quality",
            weights.response_quality,
            None if rq_score is None else round(rq_score, 4),
            rq_enabled,
            f"{int(sum(response_scores))}/{len(response_scores)} checks"
            if rq_enabled
            else "disabled: no applicable checks",
        ),
    ]
    enabled = [c for c in components if c.enabled and c.weight > 0]
    total_weight = sum(c.weight for c in enabled)
    score = (
        round(100 * sum(c.weight * (c.score or 0.0) for c in enabled) / total_weight, 1)
        if total_weight
        else 0.0
    )

    if gate_failures:
        verdict: Verdict = "FAILED_POLICY"
    elif facts.status in ("timed_out", "errored") or not has_outcome:
        verdict = "FAIL"
    elif rc_ok and not actions_missing and score >= threshold:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    return Evaluation(
        EVALUATOR_VERSION,
        verdict,
        score,
        verdict == "PASS",
        threshold,
        components,
        assertions,
        gate_failures,
    )
