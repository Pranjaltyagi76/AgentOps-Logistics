"""Regression comparison of two suite runs (context/benchmark.md §13). Pure: works only on
persisted results the caller loaded; it never re-runs or re-scores anything.

- Scenarios are paired by scenario key; a pair is comparable only when both sides used the same
  scenario version and evaluator version and neither side is a platform error.
- With repeats, each side uses its majority verdict (a tie counts as the worse verdict) and a
  scenario is `flaky` when its verdicts differ across repeats.
- Classes: fixed, newly_failed, still_passing, still_failing, not_comparable; plus the
  `safety_regression` flag when the candidate fails a safety gate the baseline passed.
"""

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.domain.metrics import RunResult, SuiteMetrics

COMPARISON_VERSION = "compare-v1"
PairClass = Literal["fixed", "newly_failed", "still_passing", "still_failing", "not_comparable"]

# Worst first: used to break ties in the majority vote.
_VERDICT_RANK = {"ERROR": 0, "FAILED_POLICY": 1, "FAIL": 2, "PASS": 3}


@dataclass(frozen=True)
class ScenarioSide:
    scenario_key: str
    versions: tuple[int, ...]
    evaluator_versions: tuple[str, ...]
    verdict: str | None
    verdicts: tuple[str, ...]
    flaky: bool
    score: float | None
    components: dict[str, float | None]
    gate_failures: tuple[str, ...]
    latency_ms: float | None
    tokens: float | None
    run_ids: tuple[str, ...]
    main_failure: str | None


@dataclass
class Pair:
    scenario_key: str
    pair_class: PairClass
    safety_regression: bool
    reason: str | None
    baseline: ScenarioSide | None
    candidate: ScenarioSide | None
    score_delta: float | None = None
    component_deltas: dict[str, float | None] = field(default_factory=dict)
    latency_delta_ms: float | None = None
    tokens_delta: float | None = None
    new_gate_failures: tuple[str, ...] = ()


@dataclass
class Comparison:
    pairs: list[Pair]
    counts: dict[str, int]
    safety_regressions: int
    regression_rate: float | None
    metric_deltas: dict[str, float | None]
    warnings: list[str]
    version: str = COMPARISON_VERSION

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def majority_verdict(verdicts: list[str]) -> str | None:
    if not verdicts:
        return None
    counts = Counter(verdicts)
    best = max(counts.values())
    tied = [v for v, c in counts.items() if c == best]
    return min(tied, key=lambda v: _VERDICT_RANK.get(v, -1))


def summarize_side(scenario_key: str, runs: list[RunResult]) -> ScenarioSide:
    scored = [r for r in runs if r.verdict is not None]
    verdicts = [r.verdict for r in scored if r.verdict is not None]
    gate_counts = Counter(g for r in scored for g in r.gate_failures)
    component_names = {name for r in scored for name in r.components}
    return ScenarioSide(
        scenario_key=scenario_key,
        versions=tuple(sorted({r.scenario_version for r in runs})),
        evaluator_versions=tuple(
            sorted({r.evaluator_version for r in scored if r.evaluator_version})
        ),
        verdict=majority_verdict(verdicts),
        verdicts=tuple(verdicts),
        flaky=len(set(verdicts)) > 1,
        score=_mean([r.score for r in scored if r.score is not None]),
        components={
            name: _mean([c for r in scored if (c := r.components.get(name)) is not None])
            for name in sorted(component_names)
        },
        # A gate counts when it failed in more than half of the repeats.
        gate_failures=tuple(sorted(g for g, c in gate_counts.items() if c * 2 > len(scored))),
        latency_ms=_mean([float(r.latency_ms) for r in scored if r.latency_ms is not None]),
        tokens=_mean([float(t) for r in scored if (t := r.tokens) is not None]),
        run_ids=tuple(r.run_id for r in runs),
        main_failure=next((r.main_failure for r in scored if r.main_failure), None),
    )


def _delta(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None:
        return None
    return round(candidate - baseline, 4)


def _not_comparable(base: ScenarioSide | None, cand: ScenarioSide | None) -> str | None:
    if base is None:
        return "only in the candidate suite run"
    if cand is None:
        return "only in the baseline suite run"
    if base.versions != cand.versions or len(base.versions) != 1:
        return f"scenario version differs ({base.versions} vs {cand.versions})"
    if base.verdict is None or cand.verdict is None:
        return "not scored on one side (cancelled or unfinished)"
    if base.evaluator_versions != cand.evaluator_versions or len(base.evaluator_versions) != 1:
        return (
            f"evaluator version differs ({', '.join(base.evaluator_versions)} vs "
            f"{', '.join(cand.evaluator_versions)}); re-score both runs with one version"
        )
    if "ERROR" in (base.verdict, cand.verdict):
        return "platform error on one side (not the agent's result)"
    return None


def _group(results: list[RunResult]) -> dict[str, list[RunResult]]:
    groups: dict[str, list[RunResult]] = {}
    for r in results:
        groups.setdefault(r.scenario_key, []).append(r)
    return groups


def compare(
    baseline: list[RunResult],
    candidate: list[RunResult],
    baseline_metrics: SuiteMetrics,
    candidate_metrics: SuiteMetrics,
) -> Comparison:
    base_groups, cand_groups = _group(baseline), _group(candidate)
    pairs: list[Pair] = []
    for key in sorted(set(base_groups) | set(cand_groups)):
        base = summarize_side(key, base_groups[key]) if key in base_groups else None
        cand = summarize_side(key, cand_groups[key]) if key in cand_groups else None
        reason = _not_comparable(base, cand)
        if reason is not None or base is None or cand is None:
            pairs.append(Pair(key, "not_comparable", False, reason, base, cand))
            continue
        base_pass, cand_pass = base.verdict == "PASS", cand.verdict == "PASS"
        pair_class: PairClass
        if base_pass and cand_pass:
            pair_class = "still_passing"
        elif cand_pass:
            pair_class = "fixed"
        elif base_pass:
            pair_class = "newly_failed"
        else:
            pair_class = "still_failing"
        new_gates = tuple(g for g in cand.gate_failures if g not in base.gate_failures)
        pairs.append(
            Pair(
                key,
                pair_class,
                safety_regression=bool(new_gates),
                reason=None,
                baseline=base,
                candidate=cand,
                score_delta=_delta(cand.score, base.score),
                component_deltas={
                    name: _delta(cand.components.get(name), base.components.get(name))
                    for name in sorted(set(base.components) | set(cand.components))
                },
                latency_delta_ms=_delta(cand.latency_ms, base.latency_ms),
                tokens_delta=_delta(cand.tokens, base.tokens),
                new_gate_failures=new_gates,
            )
        )

    counts = Counter(p.pair_class for p in pairs)
    comparable = [p for p in pairs if p.pair_class != "not_comparable"]
    baseline_passes = sum(1 for p in comparable if p.baseline and p.baseline.verdict == "PASS")
    warnings = []
    if not comparable:
        warnings.append("No scenario can be compared between these two suite runs.")
    flaky = [p.scenario_key for p in pairs for s in (p.baseline, p.candidate) if s and s.flaky]
    if flaky:
        warnings.append(
            f"Flaky scenarios (verdict changed across repeats): {', '.join(sorted(set(flaky)))}"
        )

    base_json, cand_json = baseline_metrics.to_json(), candidate_metrics.to_json()
    metric_deltas = {
        name: _delta(cand_json[name], base_json[name])
        for name, value in base_json.items()
        if isinstance(value, int | float)
        and not isinstance(value, bool)
        and name not in ("runs", "evaluated", "errors")
    }
    return Comparison(
        pairs=pairs,
        counts={
            c: counts.get(c, 0)
            for c in ("fixed", "newly_failed", "still_passing", "still_failing", "not_comparable")
        },
        safety_regressions=sum(1 for p in pairs if p.safety_regression),
        regression_rate=round(counts.get("newly_failed", 0) / baseline_passes, 4)
        if baseline_passes
        else None,
        metric_deltas=metric_deltas,
        warnings=warnings,
    )
