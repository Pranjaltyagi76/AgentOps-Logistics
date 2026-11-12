"""Suite metrics and regression comparison: pure functions over hand-built run results."""

from typing import Any

import pytest

from app.domain.comparison import compare, majority_verdict, summarize_side
from app.domain.metrics import P95_MIN_RUNS, RunResult, percentile, suite_metrics


def result(key: str = "s1", verdict: str | None = "PASS", **kw: Any) -> RunResult:
    defaults: dict[str, Any] = {
        "run_id": f"{key}-{kw.get('repeat_index', 0)}-{verdict}",
        "scenario_key": key,
        "scenario_version": 1,
        "repeat_index": 0,
        "status": "completed",
        "verdict": verdict,
        "score": 100.0 if verdict == "PASS" else 50.0,
        "evaluator_version": "eval-v2",
        "components": {"root_cause": 1.0 if verdict == "PASS" else 0.0},
        "root_cause_ok": verdict == "PASS",
        "latency_ms": 100,
        "steps": 4,
        "calls_attempted": 4,
        "calls_valid": 4,
        "calls_executed": 4,
        "calls_succeeded": 4,
    }
    defaults.update(kw)
    return RunResult(**defaults)


# --- metrics ---------------------------------------------------------------------------------


def test_rates_over_evaluated_runs_only() -> None:
    runs = [
        result("a", "PASS"),
        result("b", "FAIL", root_cause_ok=True),
        result("c", "FAILED_POLICY", gate_failures=("no_forbidden_action",)),
        result("d", "ERROR", status="errored", latency_ms=None),
        result("e", None, status="cancelled", latency_ms=None),
    ]
    m = suite_metrics(runs)
    assert (m.runs, m.evaluated, m.errors) == (5, 3, 1)
    assert m.task_success_rate == round(1 / 3, 4)
    assert m.root_cause_accuracy == round(2 / 3, 4)
    assert m.policy_violation_rate == round(1 / 3, 4)
    assert m.infra_error_rate == 0.25  # 1 ERROR of 4 scored runs
    assert m.verdicts == {"PASS": 1, "FAIL": 1, "FAILED_POLICY": 1, "ERROR": 1}
    assert m.mean_score == round((100 + 50 + 50) / 3, 2)


def test_evidence_recall_is_micro_averaged() -> None:
    runs = [
        result("a", evidence_required=3, evidence_found=3),
        result("b", evidence_required=1, evidence_found=0),
        result("c", evidence_required=0, evidence_found=0),  # no required evidence: ignored
    ]
    assert suite_metrics(runs).evidence_recall == 0.75


def test_tool_call_precision_and_success() -> None:
    runs = [
        result("a", calls_attempted=5, calls_valid=4, calls_executed=4, calls_succeeded=3),
        result("b", calls_attempted=5, calls_valid=5, calls_executed=5, calls_succeeded=5),
    ]
    m = suite_metrics(runs)
    assert (m.tool_call_precision, m.tool_call_success_rate) == (0.9, round(8 / 9, 4))


def test_escalation_precision_and_recall_and_their_unknowns() -> None:
    runs = [
        result("tp", escalation_expected=True, escalated=True),
        result("fp", escalation_expected=False, escalated=True),
        result("fn", escalation_expected=True, escalated=False),
        result("tn", escalation_expected=False, escalated=False),
    ]
    m = suite_metrics(runs)
    assert (m.escalation_precision, m.escalation_recall) == (0.5, 0.5)
    none = suite_metrics([result("tn", escalation_expected=False, escalated=False)])
    assert (none.escalation_precision, none.escalation_recall) == (None, None)


def test_latency_p95_needs_enough_runs_and_cost_stays_unknown() -> None:
    few = suite_metrics([result(f"s{i}", latency_ms=100 * i) for i in range(1, 6)])
    assert few.mean_latency_ms == 300.0 and few.p95_latency_ms is None
    many = suite_metrics([result(f"s{i}", latency_ms=i) for i in range(1, P95_MIN_RUNS + 1)])
    assert many.p95_latency_ms == 19.0  # nearest rank
    assert many.estimated_cost_usd is None
    assert percentile([5, 1, 3], 50) == 3


def test_tokens_only_when_every_run_reports_them() -> None:
    known = suite_metrics(
        [
            result("a", input_tokens=100, output_tokens=10),
            result("b", input_tokens=200, output_tokens=20),
        ]
    )
    assert known.mean_tokens == 165.0
    partial = suite_metrics([result("a", input_tokens=100, output_tokens=10), result("b")])
    assert partial.mean_tokens is None


def test_empty_suite_is_all_unknown() -> None:
    m = suite_metrics([])
    assert m.task_success_rate is None and m.mean_latency_ms is None and m.verdicts == {}


# --- majority and flakiness --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [
        (["PASS", "PASS", "FAIL"], "PASS"),
        (["PASS", "FAIL"], "FAIL"),  # a tie counts as the worse verdict
        (["PASS", "FAILED_POLICY", "FAIL"], "FAILED_POLICY"),
        ([], None),
    ],
)
def test_majority_verdict(verdicts: list[str], expected: str | None) -> None:
    assert majority_verdict(verdicts) == expected


def test_repeats_mark_a_scenario_flaky() -> None:
    side = summarize_side(
        "s1",
        [
            result("s1", "PASS", repeat_index=0),
            result("s1", "FAIL", repeat_index=1),
            result("s1", "PASS", repeat_index=2),
        ],
    )
    assert (side.verdict, side.flaky, side.verdicts) == ("PASS", True, ("PASS", "FAIL", "PASS"))
    steady = summarize_side("s1", [result("s1", "PASS", repeat_index=i) for i in range(3)])
    assert steady.flaky is False


def test_a_gate_counts_when_it_fails_in_most_repeats() -> None:
    gate = ("no_forbidden_action",)
    once = summarize_side(
        "s1",
        [
            result("s1", "FAILED_POLICY", gate_failures=gate),
            result("s1", "PASS", repeat_index=1),
            result("s1", "PASS", repeat_index=2),
        ],
    )
    assert once.gate_failures == ()
    mostly = summarize_side(
        "s1",
        [
            result("s1", "FAILED_POLICY", gate_failures=gate),
            result("s1", "FAILED_POLICY", gate_failures=gate, repeat_index=1),
            result("s1", "PASS", repeat_index=2),
        ],
    )
    assert mostly.gate_failures == gate


# --- comparison --------------------------------------------------------------------------------


def run_compare(base: list[RunResult], cand: list[RunResult]):  # type: ignore[no-untyped-def]
    return compare(base, cand, suite_metrics(base), suite_metrics(cand))


def classes(comparison: Any) -> dict[str, str]:
    return {p.scenario_key: p.pair_class for p in comparison.pairs}


def test_every_class_and_the_safety_regression_flag() -> None:
    gate = ("constraint:must_not_invent_eta",)
    base = [
        result("fixed", "FAIL"),
        result("broke", "PASS"),
        result("same_ok", "PASS"),
        result("same_bad", "FAIL"),
        result("unsafe", "PASS"),
    ]
    cand = [
        result("fixed", "PASS"),
        result("broke", "FAIL"),
        result("same_ok", "PASS"),
        result("same_bad", "FAIL"),
        result("unsafe", "FAILED_POLICY", gate_failures=gate),
    ]
    c = run_compare(base, cand)
    assert classes(c) == {
        "broke": "newly_failed",
        "fixed": "fixed",
        "same_bad": "still_failing",
        "same_ok": "still_passing",
        "unsafe": "newly_failed",
    }
    unsafe = next(p for p in c.pairs if p.scenario_key == "unsafe")
    assert unsafe.safety_regression and unsafe.new_gate_failures == gate
    assert c.safety_regressions == 1
    assert c.counts == {
        "fixed": 1,
        "newly_failed": 2,
        "still_passing": 1,
        "still_failing": 1,
        "not_comparable": 0,
    }
    assert c.regression_rate == round(2 / 3, 4)  # 2 of the 3 baseline passes broke
    fixed = next(p for p in c.pairs if p.scenario_key == "fixed")
    assert fixed.score_delta == 50.0 and fixed.component_deltas == {"root_cause": 1.0}
    assert c.metric_deltas["task_success_rate"] == round(2 / 5 - 3 / 5, 4)


def test_a_gate_the_baseline_also_failed_is_not_a_regression() -> None:
    gate = ("no_forbidden_action",)
    c = run_compare(
        [result("s", "FAILED_POLICY", gate_failures=gate)],
        [result("s", "FAILED_POLICY", gate_failures=gate)],
    )
    assert classes(c) == {"s": "still_failing"} and c.safety_regressions == 0


@pytest.mark.parametrize(
    ("base", "cand", "reason"),
    [
        (result("s", scenario_version=1), result("s", scenario_version=2), "scenario version"),
        (result("s"), result("s", evaluator_version="eval-v1"), "evaluator version"),
        (result("s"), result("s", "ERROR", status="errored"), "platform error"),
        (result("s"), result("s", None, status="cancelled"), "not scored"),
    ],
)
def test_mismatches_are_not_comparable(base: RunResult, cand: RunResult, reason: str) -> None:
    pair = run_compare([base], [cand]).pairs[0]
    assert pair.pair_class == "not_comparable" and reason in (pair.reason or "")
    assert pair.safety_regression is False and pair.score_delta is None


def test_scenarios_on_one_side_only() -> None:
    c = run_compare([result("a"), result("b")], [result("a"), result("c")])
    reasons = {p.scenario_key: p.reason for p in c.pairs if p.pair_class == "not_comparable"}
    assert reasons == {
        "b": "only in the baseline suite run",
        "c": "only in the candidate suite run",
    }


def test_nothing_comparable_and_flaky_warnings() -> None:
    c = run_compare([result("a")], [result("b")])
    assert c.regression_rate is None
    assert any("No scenario can be compared" in w for w in c.warnings)
    flaky = run_compare([result("a"), result("a", "FAIL", repeat_index=1)], [result("a")])
    assert any("Flaky scenarios" in w and "a" in w for w in flaky.warnings)
