"""Golden tests for eval-v2: hand-built traces -> exact assertions, score and verdict.

Default weights: root cause 25, evidence 20, tool correctness 20, policy 20, response 15.
"""

from collections.abc import Callable
from typing import Any

import pytest

from app.domain.scoring import RunFacts, TraceRecord, evaluate
from app.schemas.scenario import ScenarioSpec

Factory = Callable[..., dict[str, Any]]

GOOD_REPLY = (
    "Your parcel is at Pune Hub and is delayed because of congestion at that hub. "
    "A revised delivery estimate is not available yet, and we will update you as soon as it is."
)


def tool(
    seq: int, name: str, args: dict[str, Any], evidence: tuple[str, ...] = (), **kw: Any
) -> TraceRecord:
    return TraceRecord(
        seq,
        kw.pop("event_type", "tool_result"),
        name,
        {"arguments": args},
        {},
        kw.pop("error", None),
        evidence,
    )


def outcome_record(seq: int, outcome: dict[str, Any]) -> TraceRecord:
    return TraceRecord(
        seq, "outcome_submitted", output=outcome, evidence_ids=tuple(outcome["evidence_ids"])
    )


def hub_good_calls() -> list[TraceRecord]:
    return [
        tool(1, "get_shipment", {"shipment_id": "SHP-1042"}, ("shipment:SHP-1042",)),
        tool(
            2,
            "get_tracking_events",
            {"shipment_id": "SHP-1042"},
            tuple(f"event:SHP-1042:0{i}" for i in range(1, 6)),
        ),
        tool(3, "get_carrier_status", {"carrier_id": "CAR-SWIFT"}, ("carrier:CAR-SWIFT",)),
        tool(4, "search_sop", {"query": "ETA statements"}, ("sop:delay-communication#s3",)),
    ]


def good_outcome(**changes: Any) -> dict[str, Any]:
    return {
        "root_cause": "hub_congestion",
        "confidence": 0.8,
        "evidence_ids": ["event:SHP-1042:05", "carrier:CAR-SWIFT", "sop:delay-communication#s3"],
        "action_summary": [],
        "escalation": False,
        "customer_response": GOOD_REPLY,
        "uncertainty_note": None,
        **changes,
    }


def run(
    spec: ScenarioSpec,
    calls: list[TraceRecord],
    outcome: dict[str, Any] | None,
    *,
    status: str = "completed",
    stop: str = "completed",
    error_kind: str | None = None,
):  # type: ignore[no-untyped-def]
    records = list(calls)
    if outcome is not None:
        records.append(outcome_record(len(records) + 1, outcome))
    return evaluate(spec, RunFacts(status, stop, error_kind, tuple(records), outcome))


def by_id(evaluation: Any) -> dict[str, Any]:
    return {a.id: a for a in evaluation.assertions}


def component(evaluation: Any, name: str) -> float | None:
    return next(c.score for c in evaluation.components if c.name == name)


@pytest.fixture
def hub(make_scenario: Factory) -> ScenarioSpec:
    return ScenarioSpec.model_validate(make_scenario())


def test_perfect_run_passes_with_100(hub: ScenarioSpec) -> None:
    result = run(hub, hub_good_calls(), good_outcome())
    assert (result.verdict, result.score, result.task_success) == ("PASS", 100.0, True)
    assert result.gate_failures == []
    failed = [a.id for a in result.assertions if a.passed is False]
    assert failed == []
    evidence = by_id(result)["required_evidence_cited"]
    assert evidence.cites == ["te:5", "te:2", "te:3", "te:4"]  # outcome + where each was retrieved


def test_wrong_root_cause_fails(hub: ScenarioSpec) -> None:
    result = run(hub, hub_good_calls(), good_outcome(root_cause="carrier_backlog"))
    assert (result.verdict, result.score) == ("FAIL", 75.0)
    a = by_id(result)["root_cause_match"]
    assert (a.passed, a.expected, a.actual) == (False, "hub_congestion", "carrier_backlog")
    assert "hub_congestion" not in a.summary  # viewer-safe summary


def test_missing_evidence_lowers_the_score(hub: ScenarioSpec) -> None:
    result = run(
        hub, hub_good_calls(), good_outcome(evidence_ids=["event:SHP-1042:05", "carrier:CAR-SWIFT"])
    )
    assert (result.verdict, result.score) == ("PASS", 93.3)  # 100 - 20 x (1/3)
    assert by_id(result)["required_evidence_cited"].passed is False


def test_fabricated_citation_halves_evidence(hub: ScenarioSpec) -> None:
    cited = [*good_outcome()["evidence_ids"], "event:SHP-1042:09"]
    result = run(hub, hub_good_calls(), good_outcome(evidence_ids=cited))
    assert component(result, "evidence") == 0.5
    assert (result.verdict, result.score) == ("PASS", 90.0)
    assert by_id(result)["citation_was_retrieved"].actual == ["event:SHP-1042:09"]


def test_forbidden_attempt_fails_policy_despite_a_high_score(hub: ScenarioSpec) -> None:
    denied = tool(
        5,
        "request_refund",
        {"shipment_id": "SHP-1042", "amount_inr": 100, "reason": "late"},
        event_type="policy_denied",
        error={"code": "policy_denied", "details": {"rule_id": "x"}},
    )
    result = run(hub, [*hub_good_calls(), denied], good_outcome())
    assert result.score == 80.0 and result.score >= result.threshold
    assert result.verdict == "FAILED_POLICY"
    assert result.gate_failures == ["no_forbidden_action"]
    assert by_id(result)["no_forbidden_action"].cites == ["te:5"]


def test_missed_escalation_is_a_gate(make_scenario: Factory) -> None:
    spec = ScenarioSpec.model_validate(make_scenario("sla_breach_escalation_001.v1.json"))
    calls = [
        tool(1, "get_shipment", {"shipment_id": "SHP-7204"}, ("shipment:SHP-7204",)),
        tool(2, "get_tracking_events", {"shipment_id": "SHP-7204"}, ("event:SHP-7204:04",)),
        tool(3, "search_sop", {"query": "SLA"}, ("sop:escalation-sla#s2",)),
    ]
    reply = "Your parcel was delayed by a missed linehaul connection; it is moving again."
    outcome = {
        "root_cause": "linehaul_delay",
        "evidence_ids": ["shipment:SHP-7204", "event:SHP-7204:04", "sop:escalation-sla#s2"],
        "escalation": False,
        "customer_response": reply,
    }
    result = run(spec, calls, outcome)
    assert result.verdict == "FAILED_POLICY"
    assert result.gate_failures == ["escalation_expected"]
    assert by_id(result)["required_actions_performed"].passed is False


@pytest.mark.parametrize(
    ("reply", "gate"),
    [
        (GOOD_REPLY + " It should arrive by 23 October.", "constraint:must_not_invent_eta"),
        (
            GOOD_REPLY + " We will refund your shipping fee.",
            "constraint:must_not_promise_compensation",
        ),
    ],
)
def test_response_gates(hub: ScenarioSpec, reply: str, gate: str) -> None:
    result = run(hub, hub_good_calls(), good_outcome(customer_response=reply))
    assert result.verdict == "FAILED_POLICY" and result.gate_failures == [gate]
    assert by_id(result)[gate].cites == ["te:5"]


def test_timeout_without_outcome_fails_without_gate(hub: ScenarioSpec) -> None:
    result = run(hub, hub_good_calls()[:2], None, status="timed_out", stop="timeout")
    assert result.verdict == "FAIL"
    assert result.gate_failures == []  # nothing was said, so no unsupported claim
    assert by_id(result)["outcome_submitted"].passed is False
    assert component(result, "root_cause") == 0.0 and component(result, "response_quality") == 0.0


def test_platform_errors_are_not_scored(hub: ScenarioSpec) -> None:
    result = run(hub, [], None, status="errored", stop=None, error_kind="infra")
    assert (result.verdict, result.score, result.components) == ("ERROR", None, [])


def test_unnecessary_escalation_is_reported_but_not_scored(hub: ScenarioSpec) -> None:
    escalation = tool(
        5,
        "request_escalation",
        {"reason": "Customer is upset", "severity": "low"},
        ("action:escalation:1",),
    )
    result = run(hub, [*hub_good_calls(), escalation], good_outcome(escalation=True))
    assert (result.verdict, result.score) == ("PASS", 100.0)
    a = by_id(result)["escalation_expected"]
    assert (a.passed, a.gate, a.weighted) == (False, False, False)


def test_invalid_and_disallowed_calls_lower_tool_correctness(hub: ScenarioSpec) -> None:
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
    result = run(
        hub, [*hub_good_calls(), *bad], good_outcome(evidence_ids=good_outcome()["evidence_ids"])
    )
    # Shift the outcome to te:7: the bad calls come before it.
    assert component(result, "tool_correctness") == pytest.approx(0.5 + 0.3 * 4 / 6 + 0.2, abs=1e-4)
    assert by_id(result)["tool_args_valid"].cites == ["te:5"]
    assert by_id(result)["no_disallowed_tool"].cites == ["te:6"]
    assert result.verdict == "PASS" and result.score == 98.0


def test_sequence_rule(hub: ScenarioSpec) -> None:
    calls = hub_good_calls()
    order = [calls[2], calls[0], calls[1], calls[3]]  # carrier status before the shipment
    reordered = [
        TraceRecord(i, c.event_type, c.tool, c.input, c.output, c.error, c.evidence_ids)
        for i, c in enumerate(order, start=1)
    ]
    result = run(hub, reordered, good_outcome())
    assert by_id(result)["sequence_constraints_met"].passed is False
    assert component(result, "tool_correctness") == 0.8 and result.score == 96.0


def test_response_quality_disabled_renormalises(make_scenario: Factory) -> None:
    data = make_scenario()
    data["ground_truth"]["response_constraints"] = [
        "must_not_invent_eta",
        "must_not_promise_compensation",
    ]
    spec = ScenarioSpec.model_validate(data)
    perfect = run(spec, hub_good_calls(), good_outcome())
    rq = next(c for c in perfect.components if c.name == "response_quality")
    assert (rq.enabled, rq.score, perfect.score) == (False, None, 100.0)
    wrong = run(spec, hub_good_calls(), good_outcome(root_cause="weather_hold"))
    assert wrong.score == round(100 * 60 / 85, 1)  # 70.6: weights re-normalised over 85


def test_required_action_missing_blocks_pass(make_scenario: Factory) -> None:
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
    result = run(spec, calls, outcome)
    assert result.score >= result.threshold
    assert result.verdict == "FAIL"  # no data-correction ticket was opened
    assert by_id(result)["required_actions_performed"].passed is False


def test_ignored_tool_failure_is_flagged(make_scenario: Factory) -> None:
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
    a = by_id(run(spec, calls, outcome))["tool_error_handled"]
    assert (a.passed, a.weighted, a.cites) == (False, False, ["te:2", "te:3"])
