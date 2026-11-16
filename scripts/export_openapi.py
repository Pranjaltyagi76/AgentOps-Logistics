"""Write the API's OpenAPI schema to frontend/openapi.json (input for generated frontend types).

Usage (from backend/):
    uv run python ../scripts/export_openapi.py          # write the file
    uv run python ../scripts/export_openapi.py --check  # exit 1 if the file is out of date (CI)

The schema is built from the app's routes; no database or server is needed. After changing an
API model, run this and then `npm run gen:api` in frontend/ to refresh src/lib/api-schema.ts.
"""

import argparse
import json
import sys
from pathlib import Path

from app.core.config import Settings
from app.main import create_app

TARGET = Path(__file__).resolve().parents[1] / "frontend" / "openapi.json"


def render() -> str:
    app = create_app(Settings(_env_file=None, app_env="test"))  # type: ignore[call-arg]
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the file is out of date")
    args = parser.parse_args(argv)
    schema = render()
    current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
    if args.check:
        if current != schema:
            print(f"{TARGET} is out of date: run scripts/export_openapi.py and npm run gen:api")
            return 1
        print("openapi.json is up to date")
        return 0
    TARGET.write_text(schema, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET} ({len(schema):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
