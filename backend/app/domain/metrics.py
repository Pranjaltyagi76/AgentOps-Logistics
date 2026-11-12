"""Suite metrics (context/benchmark.md §9). Pure: computed from facts the caller loaded from
persisted runs, evaluations and trace events, so they can always be recomputed.

"Evaluated" runs are those with a verdict other than ERROR (cancelled runs have none). Every
metric that cannot be measured is None ("unknown"), never 0.
"""

import math
from dataclasses import asdict, dataclass, field
from typing import Any

METRICS_VERSION = "metrics-v1"
P95_MIN_RUNS = 20


@dataclass(frozen=True)
class RunResult:
    """One run as the metrics and the comparison see it."""

    run_id: str
    scenario_key: str
    scenario_version: int
    repeat_index: int
    status: str
    verdict: str | None  # None: not scored (cancelled / still running)
    score: float | None = None
    evaluator_version: str | None = None
    components: dict[str, float | None] = field(default_factory=dict)
    gate_failures: tuple[str, ...] = ()
    root_cause_ok: bool | None = None
    evidence_required: int = 0
    evidence_found: int = 0
    escalation_expected: bool | None = None
    escalated: bool | None = None
    calls_attempted: int = 0
    calls_valid: int = 0
    calls_executed: int = 0
    calls_succeeded: int = 0
    latency_ms: int | None = None
    steps: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    main_failure: str | None = None

    @property
    def evaluated(self) -> bool:
        return self.verdict is not None and self.verdict != "ERROR"

    @property
    def tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class SuiteMetrics:
    runs: int
    evaluated: int
    errors: int
    task_success_rate: float | None
    root_cause_accuracy: float | None
    evidence_recall: float | None
    tool_call_precision: float | None
    tool_call_success_rate: float | None
    policy_violation_rate: float | None
    escalation_precision: float | None
    escalation_recall: float | None
    infra_error_rate: float | None
    mean_latency_ms: float | None
    p95_latency_ms: float | None
    mean_steps: float | None
    mean_tool_calls: float | None
    mean_tokens: float | None
    estimated_cost_usd: float | None  # no verified price list yet: always unknown
    mean_score: float | None
    verdicts: dict[str, int]
    version: str = METRICS_VERSION

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _ratio(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile."""
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def suite_metrics(results: list[RunResult]) -> SuiteMetrics:
    scored = [r for r in results if r.verdict is not None]
    evaluated = [r for r in scored if r.evaluated]
    errors = [r for r in scored if r.verdict == "ERROR"]
    n = len(evaluated)

    verdicts: dict[str, int] = {}
    for r in scored:
        verdicts[r.verdict or ""] = verdicts.get(r.verdict or "", 0) + 1

    with_evidence = [r for r in evaluated if r.evidence_required]
    tp = sum(1 for r in evaluated if r.escalated and r.escalation_expected)
    fp = sum(1 for r in evaluated if r.escalated and r.escalation_expected is False)
    fn = sum(1 for r in evaluated if not r.escalated and r.escalation_expected)
    expected_any = any(r.escalation_expected for r in evaluated)
    escalated_any = any(r.escalated for r in evaluated)

    completed = [r for r in results if r.latency_ms is not None and r.status == "completed"]
    latencies = [float(r.latency_ms) for r in completed if r.latency_ms is not None]
    tokens = [r.tokens for r in evaluated]

    return SuiteMetrics(
        runs=len(results),
        evaluated=n,
        errors=len(errors),
        task_success_rate=_ratio(sum(1 for r in evaluated if r.verdict == "PASS"), n),
        root_cause_accuracy=_ratio(sum(1 for r in evaluated if r.root_cause_ok), n),
        evidence_recall=_ratio(
            sum(r.evidence_found for r in with_evidence),
            sum(r.evidence_required for r in with_evidence),
        ),
        tool_call_precision=_ratio(
            sum(r.calls_valid for r in evaluated), sum(r.calls_attempted for r in evaluated)
        ),
        tool_call_success_rate=_ratio(
            sum(r.calls_succeeded for r in evaluated), sum(r.calls_executed for r in evaluated)
        ),
        policy_violation_rate=_ratio(sum(1 for r in evaluated if r.gate_failures), n),
        escalation_precision=_ratio(tp, tp + fp) if escalated_any else None,
        escalation_recall=_ratio(tp, tp + fn) if expected_any else None,
        infra_error_rate=_ratio(len(errors), len(scored)),
        mean_latency_ms=_mean(latencies),
        p95_latency_ms=percentile(latencies, 95) if len(latencies) >= P95_MIN_RUNS else None,
        mean_steps=_mean([float(r.steps) for r in evaluated if r.steps is not None]),
        mean_tool_calls=_mean([float(r.calls_attempted) for r in evaluated]) if n else None,
        mean_tokens=_mean([float(t) for t in tokens if t is not None])
        if tokens and all(t is not None for t in tokens)
        else None,
        estimated_cost_usd=None,
        mean_score=_mean([r.score for r in evaluated if r.score is not None]),
        verdicts=verdicts,
    )
