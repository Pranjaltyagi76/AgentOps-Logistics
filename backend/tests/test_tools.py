"""Tool gateway, handlers and fault injection, run against the real scenario files.

SOP search is replaced by a stub here; the Postgres search is tested in test_sop_search.py.
"""

import dataclasses
from collections.abc import Callable
from typing import Any

import pytest

from app.domain.taxonomy import evidence_kind
from app.schemas.scenario import ScenarioSpec
from app.services.sops.service import SopHit
from app.services.tools.data_view import ScenarioDataView
from app.services.tools.gateway import ToolCallRecord, ToolGateway
from app.services.tools.registry import REGISTRY, tool_specs

Factory = Callable[..., dict[str, Any]]


class StubSearcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, frozenset[str], int]] = []

    def search(self, query: str, allowed_slugs: frozenset[str], top_k: int) -> list[SopHit]:
        self.calls.append((query, allowed_slugs, top_k))
        slug = sorted(allowed_slugs)[0]
        return [SopHit(f"sop:{slug}#s1", slug, "Doc", "s1", "Section", "Body text.", 1.5)]


class Recorder:
    def __init__(self) -> None:
        self.records: list[ToolCallRecord] = []

    def on_tool_call(self, record: ToolCallRecord) -> None:
        self.records.append(record)


def gateway(data: dict[str, Any], sleeps: list[float] | None = None, **kwargs: Any) -> ToolGateway:
    view = ScenarioDataView.from_spec(ScenarioSpec.model_validate(data))
    sleep_log = sleeps if sleeps is not None else []
    return ToolGateway.for_scenario(view, StubSearcher(), sleep=sleep_log.append, **kwargs)


# --- golden: every required record evidence is reachable through the tools ---------------


def test_required_record_evidence_is_reachable_in_every_scenario(
    scenario_files: dict[str, dict[str, Any]],
) -> None:
    for name, data in scenario_files.items():
        gw = gateway(data, max_tool_calls=100)
        mock = data["mock_data"]
        collected: set[str] = set()
        for shipment in mock["shipments"]:
            for tool in ("get_shipment", "get_tracking_events"):
                if tool in gw.permitted_tools:
                    collected |= set(
                        getattr(
                            gw.call(tool, {"shipment_id": shipment["shipment_id"]}),
                            "evidence_ids",
                            [],
                        )
                    )
        for carrier in mock["carrier_status"]:
            if "get_carrier_status" in gw.permitted_tools:
                collected |= set(
                    getattr(
                        gw.call("get_carrier_status", {"carrier_id": carrier["carrier_id"]}),
                        "evidence_ids",
                        [],
                    )
                )
        for ticket in mock["tickets"]:
            if "get_ticket" in gw.permitted_tools:
                collected |= set(
                    getattr(
                        gw.call("get_ticket", {"ticket_id": ticket["ticket_id"]}),
                        "evidence_ids",
                        [],
                    )
                )

        required = {
            e for e in data["ground_truth"]["required_evidence"] if evidence_kind(e) != "sop"
        }
        assert required <= collected, (name, required - collected)


def test_read_tools_return_records_with_evidence_ids(make_scenario: Factory) -> None:
    gw = gateway(make_scenario())
    shipment = gw.call("get_shipment", {"shipment_id": "SHP-1042"})
    assert shipment.ok and shipment.evidence_ids == ["shipment:SHP-1042"]
    assert shipment.data["carrier_id"] == "CAR-SWIFT"

    events = gw.call("get_tracking_events", {"shipment_id": "SHP-1042"})
    assert events.ok
    assert [e["seq"] for e in events.data["events"]] == [1, 2, 3, 4, 5]
    assert events.evidence_ids[-1] == "event:SHP-1042:05"
    assert events.data["events"][-1]["event_code"] == "HUB_DELAY"

    carrier = gw.call("get_carrier_status", {"carrier_id": "CAR-SWIFT"})
    assert carrier.ok and carrier.data["status"] == "degraded"
    assert carrier.evidence_ids == ["carrier:CAR-SWIFT"]


def test_unknown_records_are_not_found(make_scenario: Factory) -> None:
    gw = gateway(make_scenario())
    for tool, args in [
        ("get_shipment", {"shipment_id": "SHP-9999"}),
        ("get_tracking_events", {"shipment_id": "SHP-9999"}),
        ("get_carrier_status", {"carrier_id": "CAR-NOPE"}),
    ]:
        outcome = gw.call(tool, args)
        assert not outcome.ok and outcome.code == "not_found", tool


def test_search_sop_is_limited_to_permitted_documents(make_scenario: Factory) -> None:
    gw = gateway(make_scenario())
    outcome = gw.call("search_sop", {"query": "ETA statements", "top_k": 2})
    assert outcome.ok
    assert outcome.evidence_ids == ["sop:delay-communication#s1"]
    _, allowed, top_k = gw.sops.calls[0]  # type: ignore[attr-defined]
    assert allowed == {"delay-communication", "escalation-sla", "response-templates"}
    assert top_k == 2


# --- gateway pipeline ---------------------------------------------------------------------


def test_unknown_and_not_permitted_tools(make_scenario: Factory) -> None:
    gw = gateway(make_scenario())
    assert gw.call("delete_database", {}).code == "unknown_tool"
    # get_ticket exists but this scenario does not make it available
    assert gw.call("get_ticket", {"ticket_id": "TKT-0001"}).code == "tool_not_permitted"


def test_agent_tool_set_narrows_permitted_tools(make_scenario: Factory) -> None:
    gw = gateway(make_scenario(), agent_tools=frozenset({"get_shipment", "get_ticket"}))
    assert gw.permitted_tools == {"get_shipment"}
    assert gw.call("get_tracking_events", {"shipment_id": "SHP-1042"}).code == "tool_not_permitted"


@pytest.mark.parametrize(
    "arguments",
    [
        {"shipment_id": "shp-1042"},  # wrong format
        {"shipment_id": "SHP-1042", "extra": True},  # unknown field
        {},  # missing field
        ["SHP-1042"],  # not an object
        None,
    ],
)
def test_invalid_arguments_are_rejected(make_scenario: Factory, arguments: Any) -> None:
    outcome = gateway(make_scenario()).call("get_shipment", arguments)
    assert not outcome.ok and outcome.code == "invalid_arguments"


def test_invalid_argument_errors_name_the_field(make_scenario: Factory) -> None:
    outcome = gateway(make_scenario()).call(
        "request_escalation", {"reason": "short", "severity": "urgent"}
    )
    fields = {e["field"] for e in outcome.details["errors"]}
    assert fields == {"reason", "severity"}


def test_forbidden_actions_are_blocked_and_recorded(make_scenario: Factory) -> None:
    recorder = Recorder()
    gw = gateway(make_scenario("policy_refund_demand_001.v1.json"), observer=recorder)
    outcome = gw.call(
        "request_refund", {"shipment_id": "SHP-8016", "amount_inr": 120, "reason": "late parcel"}
    )
    assert not outcome.ok and outcome.code == "policy_denied"
    assert outcome.details["rule_id"] == "policy-v1/refund-requires-authorization"
    assert gw.actions.actions == []  # nothing was executed
    assert recorder.records[0].policy_rule_id == "policy-v1/refund-requires-authorization"


def test_budget_counts_every_attempt(make_scenario: Factory) -> None:
    gw = gateway(make_scenario(), max_tool_calls=3)
    gw.call("get_shipment", {"shipment_id": "bad"})  # invalid, still counts
    gw.call("delete_everything", {})  # unknown, still counts
    assert gw.call("get_shipment", {"shipment_id": "SHP-1042"}).ok
    assert gw.budget_remaining == 0
    assert gw.call("get_shipment", {"shipment_id": "SHP-1042"}).code == "tool_budget_exceeded"
    assert [r.seq for r in gw.calls] == [1, 2, 3, 4]


def test_every_call_is_observed_in_order(make_scenario: Factory) -> None:
    recorder = Recorder()
    gw = gateway(make_scenario(), observer=recorder)
    gw.call("get_shipment", {"shipment_id": "SHP-1042"})
    gw.call("get_carrier_status", {"carrier_id": "CAR-SWIFT"})
    assert [(r.seq, r.tool, r.ok) for r in recorder.records] == [
        (1, "get_shipment", True),
        (2, "get_carrier_status", True),
    ]
    assert recorder.records == gw.calls


# --- fault injection ----------------------------------------------------------------------


def test_carrier_timeout_is_reproducible(make_scenario: Factory) -> None:
    data = make_scenario("carrier_api_timeout_001.v1.json")
    for _ in range(2):  # two independent runs behave identically
        sleeps: list[float] = []
        gw = gateway(data, sleeps)
        first = gw.call("get_carrier_status", {"carrier_id": "CAR-SWIFT"})
        retry = gw.call("get_carrier_status", {"carrier_id": "CAR-SWIFT"})
        assert (first.code, first.retryable) == ("timeout", True)
        assert retry.code == "timeout"
        assert sleeps == [3.0, 3.0]
        assert [r.simulated_latency_ms for r in gw.calls] == [3000, 3000]
        # Other tools are unaffected.
        assert gw.call("get_tracking_events", {"shipment_id": "SHP-6158"}).ok


def test_fault_on_specific_calls_only(make_scenario: Factory) -> None:
    data = make_scenario()
    data["fault_injection"] = [
        {"tool": "get_carrier_status", "error": "unavailable", "latency_ms": 0, "calls": [2]}
    ]
    gw = gateway(data)
    results = [gw.call("get_carrier_status", {"carrier_id": "CAR-SWIFT"}) for _ in range(3)]
    assert [r.ok for r in results] == [True, False, True]
    assert results[1].code == "unavailable"


def test_rejected_calls_do_not_consume_fault_counters(make_scenario: Factory) -> None:
    data = make_scenario()
    data["fault_injection"] = [
        {"tool": "get_carrier_status", "error": "malformed_response", "calls": [1]}
    ]
    gw = gateway(data)
    gw.call("get_carrier_status", {"carrier_id": "bad id"})  # invalid: never executed
    assert gw.call("get_carrier_status", {"carrier_id": "CAR-SWIFT"}).code == "malformed_response"


# --- mock writes --------------------------------------------------------------------------


def test_mock_writes_are_recorded_with_action_ids(make_scenario: Factory) -> None:
    gw = gateway(make_scenario("sla_breach_escalation_001.v1.json"))
    first = gw.call(
        "request_escalation",
        {
            "reason": "Express SLA breached: promised 22 Oct",
            "severity": "high",
            "shipment_id": "SHP-7204",
        },
    )
    second = gw.call("request_escalation", {"reason": "Customer chased again", "severity": "high"})
    message = gw.call("send_customer_message", {"message": "We have escalated your case."})
    assert first.evidence_ids == ["action:escalation:1"]
    assert second.evidence_ids == ["action:escalation:2"]
    assert message.data["status"] == "queued_in_outbox"
    assert [a["kind"] for a in gw.actions.actions] == ["escalation", "escalation", "message"]


def test_mock_write_for_unknown_shipment_is_not_found(make_scenario: Factory) -> None:
    gw = gateway(make_scenario("data_invalid_timestamp_001.v1.json"))
    outcome = gw.call(
        "create_support_ticket",
        {
            "category": "data_correction",
            "summary": "Future-dated delivered event",
            "shipment_id": "SHP-0000",
        },
    )
    assert outcome.code == "not_found"
    assert gw.actions.actions == []


# --- specs and isolation ------------------------------------------------------------------


def test_tool_specs_are_json_schemas_that_forbid_extra_fields() -> None:
    specs = tool_specs(REGISTRY)
    assert [s["name"] for s in specs] == list(REGISTRY)
    for spec in specs:
        assert spec["description"]
        assert spec["parameters"]["type"] == "object"
        assert spec["parameters"]["additionalProperties"] is False
    assert tool_specs({"get_shipment"})[0]["parameters"]["required"] == ["shipment_id"]


def test_data_view_cannot_reach_ground_truth() -> None:
    fields = {f.name for f in dataclasses.fields(ScenarioDataView)}
    assert not fields & {"ground_truth", "evaluation", "author_note", "expected_escalation"}
