"""Load SOP documents (data/sops), scenarios (data/scenarios) and agent configs (data/agents).

Usage (from backend/, after `uv run alembic upgrade head`):
    uv run python ../scripts/seed_db.py

Idempotent: re-running reports "unchanged" for everything that already matches the database.
Exit code 1 if the SOP files disagree with the catalog, or if any scenario fails validation or
conflicts with a locked version, or if an agent config is invalid.
"""

import json
import sys

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.domain.sop_catalog import get_catalog
from app.domain.sop_corpus import check_against_catalog, load_corpus
from app.services.agents.service import AgentConfigService
from app.services.scenarios.service import ScenarioService
from app.services.sops.service import sync_corpus


def main() -> int:
    settings = get_settings()
    catalog = get_catalog(settings.data_dir)

    corpus = load_corpus(settings.data_dir / "sops")
    problems = check_against_catalog(corpus, catalog)
    if problems:
        print("SOP files do not match data/sops/catalog.json:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    paths = sorted((settings.data_dir / "scenarios").glob("*.json"))
    items = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    agent_paths = sorted((settings.data_dir / "agents").glob("*.json"))
    agent_items = [json.loads(path.read_text(encoding="utf-8")) for path in agent_paths]
    with get_sessionmaker()() as db:
        sop_results = sync_corpus(db, corpus)
        results = ScenarioService(db, catalog).import_many(items)
        agent_results = AgentConfigService(db).import_many(agent_items)

    for slug, version, outcome in sop_results:
        print(f"{outcome:<10} sop {slug} v{version}")
    for path, result in zip(paths, results, strict=True):
        print(f"{result.outcome:<10} {path.name}")
        for error in result.errors or []:
            print(f"           - {error['loc']}: {error['msg']}")
    for path, agent in zip(agent_paths, agent_results, strict=True):
        print(f"{agent.outcome:<10} agent {path.name}")
        for error in agent.errors or []:
            print(f"           - {error['loc']}: {error['msg']}")
    failed = sum(1 for r in results if r.outcome == "error")
    failed += sum(1 for r in agent_results if r.outcome == "error")
    print(
        f"\n{len(sop_results)} SOP documents, {len(results)} scenarios, "
        f"{len(agent_results)} agent configs processed; {failed} failed"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
