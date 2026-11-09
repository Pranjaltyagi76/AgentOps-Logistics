import pytest

from app.domain.policy import PolicyEngine
from app.domain.taxonomy import ToolName


@pytest.mark.parametrize(
    ("tool", "rule"),
    [
        ("request_refund", "policy-v1/refund-requires-authorization"),
        ("request_reroute", "policy-v1/reroute-requires-authorization"),
    ],
)
def test_gated_tools_are_denied_by_default(tool: str, rule: str) -> None:
    decision = PolicyEngine().check(tool, {"shipment_id": "SHP-1042"})
    assert not decision.allowed
    assert decision.rule_id == rule
    assert decision.message


def test_explicit_authorization_allows_a_gated_tool() -> None:
    engine = PolicyEngine(authorized_tools=frozenset({"request_refund"}))
    assert engine.check("request_refund", {}).allowed
    assert not engine.check("request_reroute", {}).allowed


def test_critical_escalation_needs_a_safety_or_legal_reason() -> None:
    engine = PolicyEngine()
    late = {"severity": "critical", "reason": "Express parcel is two days late"}
    assert engine.check("request_escalation", late).rule_id == (
        "policy-v1/critical-escalation-needs-safety-or-legal-reason"
    )
    safety = {"severity": "critical", "reason": "Customer reports a safety threat at the door"}
    assert engine.check("request_escalation", safety).allowed
    assert engine.check("request_escalation", {**late, "severity": "high"}).allowed


@pytest.mark.parametrize(
    "tool", [t for t in ToolName if t not in {"request_refund", "request_reroute"}]
)
def test_other_tools_are_allowed(tool: str) -> None:
    assert PolicyEngine().check(tool, {"severity": "high", "reason": "x" * 20}).allowed
