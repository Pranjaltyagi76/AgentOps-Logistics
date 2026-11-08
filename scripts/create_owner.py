"""Create the owner account, or reset its password.

Usage (from backend/), with OWNER_EMAIL and OWNER_PASSWORD set in the environment or .env:
    uv run python ../scripts/create_owner.py

The password is read from the environment only, never from the command line (so it does not
end up in shell history). Remove OWNER_PASSWORD from the environment afterwards.
"""

import os
import sys

from dotenv import dotenv_values

from app.db.session import get_sessionmaker
from app.services.auth.service import upsert_owner


def main() -> int:
    file_values = dotenv_values(".env")
    email = os.environ.get("OWNER_EMAIL") or file_values.get("OWNER_EMAIL")
    password = os.environ.get("OWNER_PASSWORD") or file_values.get("OWNER_PASSWORD")
    if not email or not password:
        print("Set OWNER_EMAIL and OWNER_PASSWORD (environment or backend/.env) first.")
        return 1
    with get_sessionmaker()() as db:
        try:
            user, created = upsert_owner(db, email, password)
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1
    print(f"{'Created' if created else 'Updated'} owner account {user.email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
