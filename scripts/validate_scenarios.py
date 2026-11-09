"""Validate scenario JSON files against the schema and semantic rules.

Also checks that the SOP files in data/sops match data/sops/catalog.json.

Usage (from backend/):
    uv run python ../scripts/validate_scenarios.py              # all files in data/scenarios
    uv run python ../scripts/validate_scenarios.py path/to.json  # specific files

Exit code 0 when every file is valid, 1 otherwise. Also checks that each file is named
`<scenario_id>.v<version>.json` and that no (scenario_id, version) pair appears twice.
"""

import json
import sys
from pathlib import Path

from app.core.config import get_settings
from app.domain.sop_catalog import get_catalog
from app.domain.sop_corpus import SopFormatError, check_against_catalog, load_corpus
from app.schemas.scenario import validate_scenario


def main(argv: list[str]) -> int:
    settings = get_settings()
    catalog = get_catalog(settings.data_dir)
    paths = [Path(arg) for arg in argv] or sorted((settings.data_dir / "scenarios").glob("*.json"))
    if not paths:
        print("No scenario files found.")
        return 1

    failures = 0
    seen: dict[tuple[str, int], Path] = {}
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"FAIL  {path.name}: cannot read JSON ({exc})")
            failures += 1
            continue

        spec, report = validate_scenario(data, catalog)
        problems = [f"{issue.loc}: {issue.msg}" for issue in report.errors]
        if spec is not None:
            expected_name = f"{spec.scenario_id}.v{spec.version}.json"
            if path.name != expected_name:
                problems.append(f"file name should be {expected_name}")
            key = (spec.scenario_id, spec.version)
            if key in seen:
                problems.append(f"duplicate of {seen[key].name}")
            seen[key] = path

        if problems:
            failures += 1
            print(f"FAIL  {path.name}")
            for problem in problems:
                print(f"      - {problem}")
        else:
            print(f"ok    {path.name}")
        for issue in report.warnings:
            print(f"      warning {issue.loc}: {issue.msg}")

    print(f"\n{len(paths) - failures}/{len(paths)} scenario files valid")

    # The SOP text files must define exactly the sections the catalog (and scenarios) cite.
    try:
        sop_problems = check_against_catalog(load_corpus(settings.data_dir / "sops"), catalog)
    except SopFormatError as exc:
        sop_problems = [str(exc)]
    for problem in sop_problems:
        print(f"FAIL  SOP: {problem}")
    print(
        "SOP files match the catalog" if not sop_problems else "SOP files do not match the catalog"
    )
    return 1 if failures or sop_problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
