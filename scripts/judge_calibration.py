"""Calibrate the advisory LLM judge against hand labels (benchmark.md §12).

Usage (from backend/, database seeded and with stored runs):
    uv run python ../scripts/judge_calibration.py export     # write the labelling sheet
    # ... fill in human_score (0 to 1) for each row in data/calibration/judge_v1.csv ...
    uv run python ../scripts/judge_calibration.py compare    # judge labelled replies, report

`export` picks up to 20 distinct customer replies from scored runs (different agents and
scenarios, so the set spans good and bad replies) and never overwrites a sheet that already has
labels unless --force is given.

`compare` runs the judge (judge_v1) on every labelled reply that has no stored judge result yet,
stores it next to the run's evaluation (still advisory: scores are never changed), then compares
judge and human scores. Each judge call uses the Gemini daily quota (1-2 requests; the free tier
allows about 20 a day) and LLM_JUDGE_DAILY_CAP; it stops when either runs out and can be re-run
the next day to continue. Results go to data/calibration/judge_v1_results.md.
"""

import argparse
import csv
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Run
from app.db.session import get_sessionmaker
from app.domain.calibration import GOOD_THRESHOLD, MAX_MAE, MIN_ITEMS, MIN_KAPPA, MIN_SPEARMAN
from app.domain.calibration import agreement as compute_agreement
from app.services.evaluation.judge import (
    JUDGE_PROMPT_VERSION,
    LLM_JUDGE_KEY,
    judge_evaluation,
    judge_input,
)
from app.services.evaluation.service import latest_evaluation, load_run_facts
from app.services.execution.service import try_consume

DIR = Path(__file__).resolve().parents[1] / "data" / "calibration"
SHEET = DIR / f"{JUDGE_PROMPT_VERSION}.csv"
RESULTS = DIR / f"{JUDGE_PROMPT_VERSION}_results.md"
FIELDS = [
    "run_id",
    "scenario_key",
    "agent",
    "verdict",
    "rubric",
    "customer_message",
    "reply",
    "human_score",
    "human_notes",
]


def _label(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    score = float(value)
    if not 0 <= score <= 1:
        raise ValueError(f"human_score must be between 0 and 1, got {value}")
    return score


def export(limit: int, force: bool) -> int:
    if SHEET.exists() and not force:
        with SHEET.open(encoding="utf-8", newline="") as f:
            if any((row.get("human_score") or "").strip() for row in csv.DictReader(f)):
                print(f"{SHEET} already has labels; use --force to overwrite it")
                return 1
    rows, seen = [], set()
    with get_sessionmaker()() as db:
        runs = db.scalars(
            select(Run)
            .where(
                Run.final_outcome_json.is_not(None),
                Run.verdict.is_not(None),
                Run.verdict != "ERROR",
            )
            .order_by(Run.created_at.desc())
        )
        for run in runs:
            reply = (run.final_outcome_json or {}).get("customer_response", "").strip()
            if not reply or reply in seen:
                continue
            spec, facts = load_run_facts(db, run)
            payload = judge_input(spec, facts)
            seen.add(reply)
            rows.append(
                {
                    "run_id": str(run.id),
                    "scenario_key": run.scenario_key,
                    "agent": run.agent_name,
                    "verdict": run.verdict,
                    "rubric": payload["rubric"],
                    "customer_message": payload["customer_message"],
                    "reply": "\n\n".join(payload["reply"]),
                    "human_score": "",
                    "human_notes": "",
                }
            )
            if len(rows) >= limit:
                break
    DIR.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (r["scenario_key"], r["agent"]))
    with SHEET.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} replies to {SHEET}")
    print("Score each reply 0 to 1 for tone, clarity and grounding (not safety rules), using the")
    print("rubric: 1.0 excellent, 0.7 good with small issues, 0.4 noticeable problems, 0 unusable.")
    if len(rows) < MIN_ITEMS:
        print(f"Note: calibration needs {MIN_ITEMS} labelled replies; run more agents first.")
    return 0


def compare() -> int:
    if not SHEET.exists():
        print(f"{SHEET} not found: run `export` first")
        return 1
    with SHEET.open(encoding="utf-8", newline="") as f:
        sheet = list(csv.DictReader(f))
    labelled = [(row, _label(row.get("human_score") or "")) for row in sheet]
    labelled = [(row, score) for row, score in labelled if score is not None]
    if not labelled:
        print("No human_score values yet: label the sheet first")
        return 1

    settings = get_settings().model_copy(update={"llm_judge_enabled": True})
    pairs, missing, stopped = [], [], None
    with get_sessionmaker()() as db:
        for row, human in labelled:
            run = db.get(Run, row["run_id"])
            evaluation = latest_evaluation(db, run.id) if run else None
            if run is None or evaluation is None:
                missing.append(row["run_id"])
                continue
            judge = evaluation.judge_json or {}
            if judge.get("prompt_version") != JUDGE_PROMPT_VERSION and stopped is None:
                spec, facts = load_run_facts(db, run)
                try:
                    evaluation = judge_evaluation(
                        db,
                        run,
                        evaluation,
                        spec,
                        facts,
                        settings,
                        consume=lambda: try_consume(
                            db, LLM_JUDGE_KEY, settings.llm_judge_daily_cap
                        ),
                    )
                    judge = evaluation.judge_json or {}
                    print(f"judged {row['scenario_key']} ({row['agent']}): {judge.get('score')}")
                except AppError as exc:
                    stopped = f"{exc.code}: {exc.message}"
                    print(f"stopped judging: {stopped}")
            if judge.get("prompt_version") == JUDGE_PROMPT_VERSION:
                pairs.append((row, human, float(judge["score"])))

    result = compute_agreement([h for _, h, _ in pairs], [j for _, _, j in pairs])
    lines = [
        f"# Judge calibration: {JUDGE_PROMPT_VERSION}",
        "",
        f"Run {datetime.now(UTC):%Y-%m-%d %H:%M} UTC · {len(pairs)} of {len(labelled)} labelled "
        f"replies judged{f' · stopped early: {stopped}' if stopped else ''}",
        "",
        "| Measure | Value | Bar |",
        "|---|---|---|",
        f"| Mean absolute error | {result.mean_absolute_error} | ≤ {MAX_MAE} |",
        f"| Spearman rank correlation | {result.spearman} | ≥ {MIN_SPEARMAN} |",
        f"| Agreement on good (≥ {GOOD_THRESHOLD}) vs not | {result.good_agreement} | — |",
        f"| Cohen's kappa (good vs not) | {result.cohen_kappa} | ≥ {MIN_KAPPA} |",
        "",
        f"**Meets the bar: {'yes' if result.meets_bar else 'no'}**"
        + ("" if result.meets_bar else f" ({'; '.join(result.reasons)})"),
        "",
        "| Scenario | Agent | Human | Judge | Difference |",
        "|---|---|---|---|---|",
        *[
            f"| {r['scenario_key']} | {r['agent']} | {h:.2f} | {j:.2f} | {j - h:+.2f} |"
            for r, h, j in pairs
        ],
    ]
    if missing:
        lines += ["", f"Runs no longer found or not scored: {', '.join(missing)}"]
    RESULTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:13]))
    print(f"\nwrote {RESULTS}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("export", help="write the labelling sheet")
    ex.add_argument("--limit", type=int, default=MIN_ITEMS)
    ex.add_argument("--force", action="store_true", help="overwrite a sheet that has labels")
    sub.add_parser("compare", help="judge labelled replies and report agreement")
    args = parser.parse_args(argv)
    return export(args.limit, args.force) if args.command == "export" else compare()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
