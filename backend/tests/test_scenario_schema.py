from collections.abc import Callable
from typing import Any

import pytest

from app.domain.sop_catalog import SopCatalog
from app.schemas.scenario import ScenarioSpec, validate_scenario

Factory = Callable[..., dict[str, Any]]


def _errors(data: dict[str, Any], catalog: SopCatalog) -> list[str]:
    _, report = validate_scenario(data, catalog)
    return [f"{e.loc}: {e.msg}" for e in report.errors]


def test_all_seed_scenarios_are_valid(
    scenario_files: dict[str, dict[str, Any]], catalog: SopCatalog
) -> None:
    assert len(scenario_files) >= 10
    for name, data in scenario_files.items():
        spec, report = validate_scenario(data, catalog)
        assert spec is not None, (name, report.errors)
        assert name == f"{spec.scenario_id}.v{spec.version}.json"


def test_seed_scenarios_cover_every_mvp_category(
    scenario_files: dict[str, dict[str, Any]],
) -> None:
    categories = {data["category"] for data in scenario_files.values()}
    assert categories >= {
        "shipment_delay",
        "tracking_anomaly",
        "delivery_failure",
        "eta_issue",
        "carrier_integration",
        "sla_escalation",
        "safety_policy",
        "data_quality",
        "ambiguity",
    }


def test_future_dated_event_is_a_warning_not_an_error(
    make_scenario: Factory, catalog: SopCatalog
) -> None:
    spec, report = validate_scenario(make_scenario("data_invalid_timestamp_001.v1.json"), catalog)
    assert spec is not None
    assert any("future-dated" in w.msg for w in report.warnings)


def test_visible_view_hides_test_design(make_scenario: Factory) -> None:
    visible = ScenarioSpec.model_validate(make_scenario()).visible_view()
    for hidden in ("ground_truth", "evaluation", "fault_injection", "author_note"):
        assert hidden not in visible
    assert visible["customer_message"].startswith("Hi, my package SHP-1042")


# Each case mutates a valid scenario and expects a specific error message fragment.
def _mutate(path: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def apply(data: dict[str, Any]) -> None:
        target = data
        parts = path.split(".")
        for part in parts[:-1]:
            target = target[int(part)] if part.isdigit() else target[part]
        last = parts[-1]
        if last.isdigit():
            target[int(last)] = value
        else:
            target[last] = value

    return apply


INVALID_CASES: list[tuple[str, Callable[[dict[str, Any]], None], str]] = [
    ("unknown root cause", _mutate("ground_truth.root_cause", "aliens"), "root_cause"),
    ("extra field", _mutate("surprise", 1), "Extra inputs are not permitted"),
    ("naive timestamp", _mutate("as_of", "2026-10-21T15:00:00"), "timezone"),
    (
        "missing evidence record",
        _mutate("ground_truth.required_evidence", ["event:SHP-1042:09"]),
        "does not match any record",
    ),
    (
        "malformed evidence ID",
        _mutate("ground_truth.required_evidence", ["hub scan"]),
        "malformed evidence ID",
    ),
    (
        "SOP not permitted",
        _mutate("ground_truth.required_evidence", ["sop:refund-reroute#s2"]),
        "not in permitted_documents",
    ),
    (
        "SOP section missing",
        _mutate("ground_truth.required_evidence", ["sop:delay-communication#s9"]),
        "does not exist in the SOP catalog",
    ),
    ("unknown SOP document", _mutate("permitted_documents", ["made-up-doc"]), "unknown SOP"),
    (
        "forbidden tool not available",
        _mutate(
            "available_tools",
            [
                "get_shipment",
                "get_tracking_events",
                "get_carrier_status",
                "search_sop",
                "request_escalation",
            ],
        ),
        "must also be listed in available_tools",
    ),
    (
        "read tool forbidden",
        _mutate("ground_truth.forbidden_actions", ["get_shipment"]),
        "cannot be forbidden",
    ),
    (
        "required and forbidden",
        _mutate("ground_truth.required_actions", ["request_refund"]),
        "both required and forbidden",
    ),
    (
        "read tool as required action",
        _mutate("ground_truth.required_actions", ["get_shipment"]),
        "is a read tool",
    ),
    (
        "unknown response constraint",
        _mutate("ground_truth.response_constraints", ["be_nice"]),
        "unknown constraint",
    ),
    (
        "weights do not sum to 100",
        _mutate("evaluation.weights", {"root_cause": 50}),
        "must sum to 100",
    ),
    (
        "duplicate tracking event",
        _mutate("mock_data.tracking_events.1.seq", 1),
        "duplicate event",
    ),
    (
        "visible shipment unknown",
        _mutate("visible_context", {"shipment_id": "SHP-0000"}),
        "is not in mock_data.shipments",
    ),
    (
        "fault on unavailable tool",
        _mutate("fault_injection", [{"tool": "get_ticket", "error": "timeout"}]),
        "is not in available_tools",
    ),
    (
        "sequence constraint on itself",
        _mutate("ground_truth.sequence_constraints", [["get_shipment", "get_shipment"]]),
        "cannot precede itself",
    ),
    ("bad scenario_id", _mutate("scenario_id", "Delay-Hub"), "scenario_id"),
]


@pytest.mark.parametrize(
    ("label", "mutate", "expected"), INVALID_CASES, ids=[c[0] for c in INVALID_CASES]
)
def test_invalid_scenarios_are_rejected_with_precise_messages(
    label: str,
    mutate: Callable[[dict[str, Any]], None],
    expected: str,
    make_scenario: Factory,
    catalog: SopCatalog,
) -> None:
    data = make_scenario()
    mutate(data)
    errors = _errors(data, catalog)
    assert errors, f"{label}: expected a validation error"
    assert any(expected in e for e in errors), errors


def test_expected_escalation_requires_the_escalation_tool(
    make_scenario: Factory, catalog: SopCatalog
) -> None:
    data = make_scenario("sla_breach_escalation_001.v1.json")
    data["available_tools"].remove("request_escalation")
    data["ground_truth"]["required_actions"] = []
    assert any("request_escalation is not available" in e for e in _errors(data, catalog))


def test_permitted_documents_require_search_sop(
    make_scenario: Factory, catalog: SopCatalog
) -> None:
    data = make_scenario()
    data["available_tools"].remove("search_sop")
    data["ground_truth"]["required_tools"] = ["get_tracking_events", "get_carrier_status"]
    assert any("search_sop is not available" in e for e in _errors(data, catalog))
