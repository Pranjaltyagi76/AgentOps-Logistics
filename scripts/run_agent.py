"""Run an agent config against scenario files from the command line (no run records yet).

Usage (from backend/, with the database seeded so SOP search works):
    uv run python ../scripts/run_agent.py                    # rule-based-v1, all scenarios
    uv run python ../scripts/run_agent.py --agent rule-based-v2-flawed
    uv run python ../scripts/run_agent.py --scenario delay_hub_congestion_001 --verbose

The "expected" columns come from the hidden ground truth. They are shown here for developers
only; the agent never sees them. Verdict and score come from the eval-v2 evaluator, computed in
memory (no run or trace is saved).
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.domain.scoring import evaluate
from app.schemas.agent_config import AgentConfigSpec
from app.schemas.scenario import ScenarioSpec
from app.services.agent_graph.runner import run_scenario
from app.services.evaluation.service import facts_from_result
from app.services.sops.service import PostgresSopSearcher


def load_config(data_dir: Path, name: str) -> AgentConfigSpec:
    matches = sorted((data_dir / "agents").glob(f"{name}.v*.json"))
    if not matches:
        raise SystemExit(f"No agent config named {name!r} in data/agents")
    return AgentConfigSpec.model_validate(json.loads(matches[-1].read_text(encoding="utf-8")))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agent", default="rule-based-v1")
    parser.add_argument("--scenario", default="all", help="scenario_id or 'all'")
    parser.add_argument("--verbose", action="store_true", help="print tool calls and the reply")
    args = parser.parse_args(argv)

    settings = get_settings()
    config = load_config(settings.data_dir, args.agent)
    paths = sorted((settings.data_dir / "scenarios").glob("*.json"))
    specs = [ScenarioSpec.model_validate(json.loads(p.read_text(encoding="utf-8"))) for p in paths]
    if args.scenario != "all":
        specs = [s for s in specs if s.scenario_id == args.scenario]
        if not specs:
            raise SystemExit(f"Unknown scenario {args.scenario!r}")

    print(f"Agent {config.name} v{config.version} ({config.provider}:{config.model_id})\n")
    header = (
        f"{'scenario':<38} {'stop':<10} {'root cause (expected)':<46} {'esc':<11} "
        f"{'verdict':<14} score"
    )
    print(header)
    print("-" * len(header))
    failures = 0
    verdicts: Counter[str] = Counter()
    with get_sessionmaker()() as db:
        searcher = PostgresSopSearcher(db)
        for spec in specs:
            result = run_scenario(spec, config, searcher)
            gt = spec.ground_truth
            outcome = result.outcome
            if outcome is None:
                failures += 1
            cause = f"{outcome.root_cause if outcome else '-'} ({gt.root_cause.value})"
            esc = f"{outcome.escalation if outcome else '-'}/{gt.expected_escalation}"
            evaluation = evaluate(spec, facts_from_result(result))
            verdicts[evaluation.verdict] += 1
            print(
                f"{spec.scenario_id:<38} {result.stop_reason:<10} {cause:<46} {esc:<11} "
                f"{evaluation.verdict:<14} {evaluation.score}"
            )
            if args.verbose:
                for record in result.tool_calls:
                    status = "ok" if record.ok else f"ERROR {record.outcome.code}"  # type: ignore[union-attr]
                    print(f"    {record.seq:>2}. {record.tool}({record.arguments}) -> {status}")
                if outcome:
                    print(f"    evidence: {outcome.evidence_ids}")
                    print(f"    reply: {outcome.customer_response}")
                for a in evaluation.assertions:
                    if a.passed is False:
                        print(f"    FAILED {a.id}: {a.summary} {a.detail}".rstrip())
                print()
    print(f"\n{len(specs) - failures}/{len(specs)} runs submitted a valid outcome")
    print("Verdicts: " + ", ".join(f"{k} {v}" for k, v in sorted(verdicts.items())))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
