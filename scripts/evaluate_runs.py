"""Score finished runs that have no evaluation yet (or re-score all with --all).

Usage (from backend/):
    uv run python ../scripts/evaluate_runs.py          # runs recorded before Phase 5, etc.
    uv run python ../scripts/evaluate_runs.py --all    # re-score every finished run

Re-scoring with the same evaluator version replaces that version's result; a new evaluator
version adds a new result next to the old one.
"""

import argparse
import sys
from collections import Counter

from sqlalchemy import select

from app.db.models import Run
from app.db.session import get_sessionmaker
from app.services.evaluation.service import NOT_SCORED, evaluate_run


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="re-score every finished run")
    args = parser.parse_args(argv)

    verdicts: Counter[str] = Counter()
    with get_sessionmaker()() as db:
        query = select(Run.id).where(Run.status.not_in(NOT_SCORED))
        if not args.all:
            query = query.where(Run.verdict.is_(None))
        for run_id in list(db.scalars(query)):
            row = evaluate_run(db, run_id)
            if row is not None:
                verdicts[row.verdict] += 1
    total = sum(verdicts.values())
    print(
        f"Scored {total} run(s): "
        + (", ".join(f"{v} {k}" for k, v in sorted(verdicts.items())) or "none")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
