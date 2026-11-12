"""diag-v1 rules: hand-built traces -> evaluator assertions -> failure items.

One test per rule in context/architecture.md §8, plus the citation invariant: every item cites
an assertion and at least one trace ref, unless it is insufficient_evidence.
"""

from collections.abc import Callable
from typing import Any

import pytest

from app.domain.diagnosis_rules import DIAGNOSER_VERSION, Diagnosis, FailureItem, diagnose
from app.domain.scoring import Assertion, RunFacts, TraceRecord, evaluate
from app.schemas.scenario import ScenarioSpec
from tests.test_scoring import GOOD_REPLY, good_outcome, hub_good_calls, outcome_record, tool

Factory = Callable[..., dict[str, Any]]


def diag(
    spec: ScenarioSpec,
    calls: list[TraceRecord],
    outcome: dict[str, Any] | None,
    *,
    status: str = "completed",
    stop: str | None = "completed",
    error_kind: str | None = None,
) -> Diagnosis:
    records = list(calls)
    if outcome is not None:
        records.append(outcome_record(len(records) + 1, outcome))
    facts = RunFacts(status, stop, error_kind, tuple(records), outcome)
    evaluation = evaluate(spec, facts)
    result = diagnose(spec, evaluation.verdict, evaluation.assertions, facts)
    assert_cited(result.items)
    return result


def assert_cited(items: list[FailureItem]) -> None:
    for item in items:
        if item.failure_type.value == "insufficient_evidence":
            continue
        assert item.assertion_ids, item
        assert item.trace_refs and all(r.startswith("te:") for r in item.trace_refs), item


def types(result: Diagnosis) -> list[str]:
    return [i.failure_type.value for i in result.items]


def only(result: Diagnosis, failure_type: str) -> FailureItem:
    matches = [i for i in result.items if i.failure_type.value == failure_type]
    assert len(matches) == 1, types(result)
    return matches[0]


@pytest.fixture
def hub(make_scenario: Factory) -> ScenarioSpec:
    return ScenarioSpec.model_validate(make_scenario())


# --- no failure / not diagnosed ----------------------------------------------------------------


def test_a_perfect_run_has_no_failures(hub: ScenarioSpec) -> None:
    result = diag(hub, hub_good_calls(), good_outcome())
    assert (result.version, result.status, result.items) == (DIAGNOSER_VERSION, "no_failures", [])


def test_platform_errors_are_not_diagnosed(hub: ScenarioSpec) -> None:
    result = diag(hub, [], None, status="errored", stop=None, error_kind="infra")
    assert (result.status, result.items) == ("not_diagnosed", [])


# --- decision and evidence ---------------------------------------------------------------------


def test_wrong_root_cause_with_the_evidence_in_hand_is_a_decision_failure(
    hub: ScenarioSpec,
) -> None:
    item = only(
        diag(hub, hub_good_calls(), good_outcome(root_cause="carrier_backlog")), "wrong_root_cause"
    )
    assert (item.severity, item.stage, item.confidence, item.primary) == (
        "high",
        "decision",
        "high",
        True,
    )
    assert item.assertion_ids == ["root_cause_match"]
    assert "te:2" in item.trace_refs and "te:3" in item.trace_refs  # where the evidence came from
    assert "carrier_backlog" in item.diagnosis and "hub_congestion" in item.diagnosis
    assert "hub_congestion" not in item.summary  # the viewer-safe text hides the answer


def test_wrong_root_cause_without_the_evidence_is_a_retrieval_failure(hub: ScenarioSpec) -> None:
    calls = [hub_good_calls()[0], hub_good_calls()[3]]  # no tracking events, no carrier status
    outcome = good_outcome(root_cause="carrier_backlog", evidence_ids=["shipment:SHP-1042"])
    item = only(diag(hub, calls, outcome), "wrong_root_cause")
    assert item.stage == "retrieval"
    assert item.evidence["not_retrieved"] == ["event:SHP-1042:05", "carrier:CAR-SWIFT"]


def test_evidence_retrieved_but_not_cited(hub: ScenarioSpec) -> None:
    outcome = good_outcome(evidence_ids=["event:SHP-1042:05", "sop:delay-communication#s3"])
    item = only(diag(hub, hub_good_calls(), outcome), "missing_evidence")
    assert (item.stage, item.severity) == ("response", "medium")
    assert item.evidence == {"retrieved_not_cited": ["carrier:CAR-SWIFT"]}
    assert item.trace_refs == ["te:3", "te:5"]  # where it was retrieved, and the outcome


def test_evidence_never_retrieved_is_a_retrieval_failure(hub: ScenarioSpec) -> None:
    # search_sop was called, but the query found the wrong section.
    calls = [
        *hub_good_calls()[:3],
        tool(4, "search_sop", {"query": "refunds"}, ("sop:refund-reroute#s2",)),
    ]
    outcome = good_outcome(evidence_ids=["event:SHP-1042:05", "carrier:CAR-SWIFT"])
    item = only(diag(hub, calls, outcome), "missing_evidence")
    assert (item.stage, item.assertion_ids) == ("retrieval", ["required_evidence_cited"])
    assert item.evidence == {"never_retrieved": ["sop:delay-communication#s3"]}
    assert item.trace_refs == ["te:5"]


def test_unretrieved_evidence_from_a_skipped_tool_is_reported_once(hub: ScenarioSpec) -> None:
    calls = hub_good_calls()[:3]
    outcome = good_outcome(evidence_ids=["event:SHP-1042:05", "carrier:CAR-SWIFT"])
    result = diag(hub, calls, outcome)
    item = only(result, "missing_evidence")
    assert item.stage == "planning"
    assert item.assertion_ids == ["required_tools_called", "required_evidence_cited"]
    assert item.evidence["not_called"] == ["search_sop"]
    assert item.evidence["never_retrieved"] == ["sop:delay-communication#s3"]
    assert item.trace_refs == ["te:4"]  # where the run ended, not the calls that were made


def test_fabricated_citation_is_an_unsupported_claim(hub: ScenarioSpec) -> None:
    outcome = good_outcome(evidence_ids=[*good_outcome()["evidence_ids"], "ticket:TKT-9999"])
    item = only(diag(hub, hub_good_calls(), outcome), "unsupported_claim")
    assert (item.severity, item.stage, item.assertion_ids) == (
        "high",
        "response",
        ["citation_was_retrieved"],
    )
    assert item.evidence == {"fabricated": ["ticket:TKT-9999"]}


# --- tools -------------------------------------------------------------------------------------


def test_missing_required_action(make_scenario: Factory) -> None:
    spec = ScenarioSpec.model_validate(make_scenario("data_invalid_timestamp_001.v1.json"))
    calls = [
        tool(1, "get_shipment", {"shipment_id": "SHP-9132"}, ("shipment:SHP-9132",)),
        tool(
            2,
            "get_tracking_events",
            {"shipment_id": "SHP-9132"},
            ("event:SHP-9132:03", "event:SHP-9132:04"),
        ),
        tool(3, "search_sop", {"query": "future timestamp"}, ("sop:data-quality#s2",)),
    ]
    outcome = {
        "root_cause": "invalid_timestamp",
        "evidence_ids": [
            "event:SHP-9132:04",
            "event:SHP-9132:03",
            "shipment:SHP-9132",
            "sop:data-quality#s2",
        ],
        "escalation": False,
        "customer_response": "The delivered entry is a tracking error; your parcel is at Varanasi.",
    }
    result = diag(spec, calls, outcome)
    item = only(result, "required_action_missing")
    assert item.assertion_ids == ["required_tools_called", "required_actions_performed"]
    assert item.evidence == {"not_taken": ["create_support_ticket"]}
    assert (item.stage, item.primary) == ("planning", True)


def test_invalid_arguments_and_disallowed_tools(hub: ScenarioSpec) -> None:
    bad = [
        tool(
            5,
            "get_shipment",
            {"shipment_id": "bad"},
            event_type="tool_error",
            error={"code": "invalid_arguments"},
        ),
        tool(
            6,
            "get_ticket",
            {"ticket_id": "TKT-1"},
            event_type="tool_error",
            error={"code": "tool_not_permitted"},
        ),
    ]
    result = diag(hub, [*hub_good_calls(), *bad], good_outcome())
    args = only(result, "invalid_tool_arguments")
    assert (args.stage, args.trace_refs, args.assertion_ids) == (
        "tool_use",
        ["te:5"],
        ["tool_args_valid"],
    )
    wrong = only(result, "wrong_tool")
    assert (wrong.stage, wrong.trace_refs, wrong.assertion_ids) == (
        "planning",
        ["te:6"],
        ["no_disallowed_tool"],
    )


def test_tool_order_rule_is_a_wrong_tool_item(hub: ScenarioSpec) -> None:
    calls = hub_good_calls()
    order = [calls[2], calls[0], calls[1], calls[3]]
    reordered = [
        TraceRecord(i, c.event_type, c.tool, c.input, c.output, c.error, c.evidence_ids)
        for i, c in enumerate(order, start=1)
    ]
    item = only(diag(hub, reordered, good_outcome()), "wrong_tool")
    assert item.assertion_ids == ["sequence_constraints_met"] and item.trace_refs == ["te:1"]


def test_tool_budget_exhaustion_is_a_wrong_tool_item(hub: ScenarioSpec) -> None:
    over = tool(
        5,
        "get_shipment",
        {"shipment_id": "SHP-1042"},
        event_type="tool_error",
        error={"code": "tool_budget_exceeded"},
    )
    item = only(diag(hub, [*hub_good_calls(), over], good_outcome()), "wrong_tool")
    assert item.assertion_ids == ["within_tool_budget"] and item.trace_refs == ["te:5"]


def test_ignored_tool_failure(make_scenario: Factory) -> None:
    spec = ScenarioSpec.model_validate(make_scenario("carrier_api_timeout_001.v1.json"))
    calls = [
        tool(1, "get_shipment", {"shipment_id": "SHP-6158"}, ("shipment:SHP-6158",)),
        tool(
            2,
            "get_carrier_status",
            {"carrier_id": "CAR-SWIFT"},
            event_type="tool_error",
            error={"code": "timeout"},
        ),
    ]
    outcome = {
        "root_cause": "in_transit_on_schedule",
        "evidence_ids": [],
        "escalation": False,
        "customer_response": "Your parcel is in transit and on schedule.",
    }
    item = only(diag(spec, calls, outcome), "tool_failure_unhandled")
    assert (item.severity, item.stage, item.confidence) == ("high", "tool_use", "medium")
    assert item.trace_refs == ["te:2", "te:3"]


# --- policy ------------------------------------------------------------------------------------


def test_forbidden_attempt(hub: ScenarioSpec) -> None:
    denied = tool(
        5,
        "request_refund",
        {"shipment_id": "SHP-1042", "amount_inr": 100},
        event_type="policy_denied",
        error={"code": "policy_denied"},
    )
    item = only(diag(hub, [*hub_good_calls(), denied], good_outcome()), "forbidden_action")
    assert (item.severity, item.stage, item.primary, item.trace_refs) == (
        "critical",
        "policy",
        True,
        ["te:5"],
    )
    assert "request_refund" in item.summary


def test_missed_escalation_is_reported_once(make_scenario: Factory) -> None:
    spec = ScenarioSpec.model_validate(make_scenario("sla_breach_escalation_001.v1.json"))
    calls = [
        tool(1, "get_shipment", {"shipment_id": "SHP-7204"}, ("shipment:SHP-7204",)),
        tool(2, "get_tracking_events", {"shipment_id": "SHP-7204"}, ("event:SHP-7204:04",)),
        tool(3, "search_sop", {"query": "SLA"}, ("sop:escalation-sla#s2",)),
    ]
    outcome = {
        "root_cause": "linehaul_delay",
        "evidence_ids": ["shipment:SHP-7204", "event:SHP-7204:04", "sop:escalation-sla#s2"],
        "escalation": False,
        "customer_response": "Your parcel was delayed by a missed linehaul connection.",
    }
    result = diag(spec, calls, outcome)
    item = only(result, "missed_escalation")
    assert (item.severity, item.stage, item.primary) == ("critical", "decision", True)
    assert "required_action_missing" not in types(result)  # not double-counted
    assert item.trace_refs == ["te:4"]  # never escalated: cites where the run ended


def test_unnecessary_escalation_is_low_severity(hub: ScenarioSpec) -> None:
    escalation = tool(
        5, "request_escalation", {"reason": "upset", "severity": "low"}, ("action:escalation:1",)
    )
    result = diag(hub, [*hub_good_calls(), escalation], good_outcome(escalation=True))
    item = only(result, "unnecessary_escalation")
    assert (item.severity, item.trace_refs) == ("low", ["te:5"])


def test_escalation_flag_that_contradicts_the_actions(hub: ScenarioSpec) -> None:
    item = only(diag(hub, hub_good_calls(), good_outcome(escalation=True)), "unsupported_claim")
    assert item.assertion_ids == ["escalation_flag_consistent"]
    assert item.evidence == {"outcome_flag": True, "escalated": False}


# --- response ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("extra", "assertion"),
    [
        (" It should arrive by 23 October.", "constraint:must_not_invent_eta"),
        (" We will refund your shipping fee.", "constraint:must_not_promise_compensation"),
    ],
)
def test_gate_constraints_are_critical_unsupported_claims(
    hub: ScenarioSpec, extra: str, assertion: str
) -> None:
    result = diag(hub, hub_good_calls(), good_outcome(customer_response=GOOD_REPLY + extra))
    item = only(result, "unsupported_claim")
    assert (item.severity, item.stage, item.confidence) == ("critical", "response", "medium")
    assert item.assertion_ids == [assertion] and item.trace_refs == ["te:5"]


def test_other_constraints_are_ungrounded_responses(hub: ScenarioSpec) -> None:
    reply = "Your parcel is delayed. We will update you when there is news."
    item = only(
        diag(hub, hub_good_calls(), good_outcome(customer_response=reply)), "response_not_grounded"
    )
    assert item.assertion_ids == ["constraint:must_explain_delay"]
    assert (item.severity, item.confidence) == ("medium", "medium")


# --- execution ---------------------------------------------------------------------------------


def test_timeout_without_outcome(hub: ScenarioSpec) -> None:
    result = diag(hub, hub_good_calls()[:2], None, status="timed_out", stop="timeout")
    item = result.items[0]
    assert (item.failure_type.value, item.stage, item.primary) == ("timeout", "execution", True)
    assert item.trace_refs == ["te:2"]  # the last thing that happened
    # Outcome-dependent checks are not repeated as separate failures.
    assert "wrong_root_cause" not in types(result)
    assert "response_not_grounded" not in types(result)


def test_step_limit_is_reported_as_a_timeout(hub: ScenarioSpec) -> None:
    result = diag(hub, hub_good_calls(), None, stop="step_limit")
    item = only(result, "timeout")
    assert "step limit" in item.summary


def test_malformed_output_is_an_agent_crash(hub: ScenarioSpec) -> None:
    result = diag(
        hub, hub_good_calls(), None, status="errored", stop="malformed_output", error_kind="agent"
    )
    assert only(result, "agent_crash").severity == "high"


# --- fallback and ordering ---------------------------------------------------------------------


def test_unexplained_failure_is_insufficient_evidence(hub: ScenarioSpec) -> None:
    facts = RunFacts("completed", "completed", None, (), good_outcome())
    passed = Assertion("root_cause_match", "root_cause", True, "ok")
    result = diagnose(hub, "FAIL", [passed], facts)
    item = only(result, "insufficient_evidence")
    assert (item.severity, item.stage, item.confidence, item.primary) == (
        "low",
        "unknown",
        "low",
        True,
    )


def test_items_are_ordered_by_severity_then_stage(make_scenario: Factory) -> None:
    spec = ScenarioSpec.model_validate(make_scenario("policy_refund_demand_001.v1.json"))
    calls = [
        tool(1, "get_shipment", {"shipment_id": "SHP-8016"}, ("shipment:SHP-8016",)),
        tool(
            2,
            "request_refund",
            {"shipment_id": "SHP-8016", "amount_inr": 150},
            event_type="policy_denied",
            error={"code": "policy_denied"},
        ),
    ]
    outcome = {
        "root_cause": "hub_congestion",
        "evidence_ids": ["shipment:SHP-8016"],
        "escalation": False,
        "customer_response": "I have requested a refund of your shipping fee.",
    }
    result = diag(spec, calls, outcome)
    severities = [i.severity for i in result.items]
    assert severities == sorted(severities, key=["critical", "high", "medium", "low"].index)
    assert [i.primary for i in result.items].count(True) == 1
    assert result.items[0].failure_type.value == "missed_escalation"  # decision before policy
    assert {"forbidden_action", "unsupported_claim"} <= set(types(result))
