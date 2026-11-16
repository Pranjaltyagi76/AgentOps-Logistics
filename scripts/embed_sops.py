"""Store embeddings for the SOP sections, for hybrid retrieval (SOP_RETRIEVAL=hybrid).

Usage (from backend/, after seed_db.py; needs GEMINI_API_KEY):
    uv run python ../scripts/embed_sops.py --dry-run   # count sections that need embedding
    uv run python ../scripts/embed_sops.py

Only sections without an embedding from EMBEDDING_MODEL are sent, 50 per request, so the
whole corpus costs one embedding request and re-running it costs none. Embedding requests
use their own free-tier quota, separate from the agent's generate requests.
"""

import argparse
import sys

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.services.sops.hybrid import embed_corpus, gemini_embedder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="only count, call nothing")
    args = parser.parse_args()
    settings = get_settings()
    embedder = gemini_embedder(settings)
    if embedder is None:
        print("GEMINI_API_KEY is not set: nothing to do")
        return 1
    with get_sessionmaker()() as db:
        count = embed_corpus(db, embedder, dry_run=args.dry_run)
    verb = "need embedding" if args.dry_run else "embedded"
    print(f"{count} SOP sections {verb} with {embedder.model}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
