"""Load every scenario file in data/scenarios into the database (idempotent).

Usage (from backend/, after `uv run alembic upgrade head`):
    uv run python ../scripts/seed_db.py

Re-running reports "unchanged" for files that match the database. Exit code 1 if any file
fails validation or conflicts with a locked version.
"""

import json
import sys

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.domain.sop_catalog import get_catalog
from app.services.scenarios.service import ScenarioService


def main() -> int:
    settings = get_settings()
    paths = sorted((settings.data_dir / "scenarios").glob("*.json"))
    items = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    with get_sessionmaker()() as db:
        results = ScenarioService(db, get_catalog(settings.data_dir)).import_many(items)

    for path, result in zip(paths, results, strict=True):
        print(f"{result.outcome:<10} {path.name}")
        for error in result.errors or []:
            print(f"           - {error['loc']}: {error['msg']}")
    failed = sum(1 for r in results if r.outcome == "error")
    print(f"\n{len(results) - failed}/{len(results)} scenarios loaded")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
