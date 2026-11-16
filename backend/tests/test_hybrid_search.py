"""Hybrid SOP retrieval: embeddings, RRF fusion, fallback and the query cache (needs a database).

Uses the deterministic HashEmbedder, so no network and no quota.
"""

from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import DEFAULT_DATA_DIR, Settings
from app.db.models import DocumentChunk, QueryEmbedding
from app.domain.sop_corpus import load_corpus
from app.services.sops.embeddings import HashEmbedder, chunk_text, normalise
from app.services.sops.hybrid import (
    HYBRID_VERSION,
    LEXICAL_VERSION,
    RRF_K,
    HybridSopSearcher,
    PerCallHybridSearcher,
    build_sop_searcher,
    embed_corpus,
    query_hash,
    retrieval_version,
)
from app.services.sops.service import PerCallSopSearcher, PostgresSopSearcher, sync_corpus

pytestmark = pytest.mark.db

ALL_SLUGS = frozenset(d.slug for d in load_corpus(DEFAULT_DATA_DIR / "sops"))


class FailingEmbedder:
    model = "hash-bow-v1"  # same model as the stored vectors, so the vector path is attempted

    def embed(self, texts: list[str], task: Any) -> list[list[float]]:
        raise RuntimeError("embedding provider down")


@pytest.fixture
def synced(db_session: Session) -> Session:
    sync_corpus(db_session, load_corpus(DEFAULT_DATA_DIR / "sops"))
    return db_session


@pytest.fixture
def embedded(synced: Session) -> Session:
    embed_corpus(synced, HashEmbedder())
    return synced


def test_embed_corpus_embeds_each_section_once(synced: Session) -> None:
    sections = synced.scalar(select(func.count()).select_from(DocumentChunk))
    embedder = HashEmbedder()
    assert embed_corpus(synced, embedder, dry_run=True) == sections
    assert embedder.calls == 0  # a dry run calls nothing
    assert embed_corpus(synced, embedder, batch_size=20) == sections
    assert embedder.calls == -(-sections // 20)  # one request per batch
    assert embed_corpus(synced, embedder) == 0  # nothing left to do
    stored = synced.scalars(select(DocumentChunk.embedding_model)).all()
    assert set(stored) == {"hash-bow-v1"}


def test_without_embeddings_hybrid_is_exactly_lexical(synced: Session) -> None:
    hybrid = HybridSopSearcher(synced, HashEmbedder())
    lexical = PostgresSopSearcher(synced)
    for query in ["customer demands a refund", "carrier API timed out", "the same scan twice"]:
        assert hybrid.search(query, ALL_SLUGS, 3) == lexical.search(query, ALL_SLUGS, 3)
        assert hybrid.last_mode == LEXICAL_VERSION
    assert hybrid.embedder.calls == 0  # type: ignore[attr-defined]


def test_hybrid_fuses_both_rankings(embedded: Session) -> None:
    searcher = HybridSopSearcher(embedded, HashEmbedder())
    hits = searcher.search("customer demands a refund", ALL_SLUGS, 5)
    assert searcher.last_mode == HYBRID_VERSION
    assert hits[0].evidence_id == "sop:refund-reroute#s2"
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
    # A section ranked first by both rankings scores 2 / (K + 1), the maximum.
    assert scores[0] <= round(2 / (RRF_K + 1), 6)
    assert len({h.evidence_id for h in hits}) == len(hits)


def test_hybrid_lifts_a_section_the_wording_only_paraphrases(embedded: Session) -> None:
    """Text search ranks the stale-ETA section third for a paraphrase; vectors lift it."""
    query = "the ETA has not been updated for days"
    target = "sop:eta-management#s2"
    lexical = [h.evidence_id for h in PostgresSopSearcher(embedded).search(query, ALL_SLUGS, 5)]
    searcher = HybridSopSearcher(embedded, HashEmbedder())
    hybrid = [h.evidence_id for h in searcher.search(query, ALL_SLUGS, 5)]
    assert target in lexical and target in hybrid
    assert hybrid.index(target) < lexical.index(target)


def test_hybrid_never_leaves_the_allowed_documents(embedded: Session) -> None:
    searcher = HybridSopSearcher(embedded, HashEmbedder())
    allowed = frozenset({"delay-communication"})
    hits = searcher.search("customer demands a refund", allowed, 5)
    assert hits and {h.document_slug for h in hits} == {"delay-communication"}
    assert searcher.search("refund", frozenset(), 3) == []
    assert searcher.search("!!! ??", ALL_SLUGS, 3) == []


def test_query_embeddings_are_cached(embedded: Session) -> None:
    embedder = HashEmbedder()
    first = HybridSopSearcher(embedded, embedder).search("carrier API timed out", ALL_SLUGS, 3)
    assert embedder.calls == 1
    again = HybridSopSearcher(embedded, embedder).search("Carrier  API timed OUT", ALL_SLUGS, 3)
    assert embedder.calls == 1  # same query after normalising case and spaces: from the cache
    assert first == again
    row = embedded.scalar(
        select(QueryEmbedding).where(
            QueryEmbedding.query_hash == query_hash("carrier api timed out")
        )
    )
    assert row is not None and row.model == "hash-bow-v1"


def test_embedder_failure_falls_back_to_lexical(embedded: Session) -> None:
    searcher = HybridSopSearcher(embedded, FailingEmbedder())
    hits = searcher.search("customer demands a refund", ALL_SLUGS, 3)
    assert searcher.last_mode == LEXICAL_VERSION
    assert hits == PostgresSopSearcher(embedded).search("customer demands a refund", ALL_SLUGS, 3)


def test_searcher_factory_and_recorded_retrieval_mode(
    embedded: Session, session_factory: Any
) -> None:
    lexical = Settings(sop_retrieval="lexical", gemini_api_key="test-key")
    assert isinstance(build_sop_searcher(lexical, session_factory), PerCallSopSearcher)
    assert retrieval_version(lexical, embedded) == LEXICAL_VERSION

    no_key = Settings(sop_retrieval="hybrid", gemini_api_key=None)
    assert isinstance(build_sop_searcher(no_key, session_factory), PerCallSopSearcher)
    assert retrieval_version(no_key, embedded) == LEXICAL_VERSION

    hybrid = Settings(
        sop_retrieval="hybrid", gemini_api_key="test-key", embedding_model="hash-bow-v1"
    )
    searcher = build_sop_searcher(hybrid, session_factory, HashEmbedder())
    assert isinstance(searcher, PerCallHybridSearcher)
    assert searcher.search("customer demands a refund", ALL_SLUGS, 1)[0].evidence_id == (
        "sop:refund-reroute#s2"
    )
    assert retrieval_version(hybrid, embedded) == HYBRID_VERSION
    other_model = Settings(sop_retrieval="hybrid", gemini_api_key="test-key")
    assert retrieval_version(other_model, embedded) == LEXICAL_VERSION  # nothing embedded with it


def test_chunk_text_and_normalise() -> None:
    assert chunk_text("Doc", "s2. Section", "Body") == "Doc - s2. Section\nBody"
    assert normalise([3.0, 4.0]) == [0.6, 0.8]
    assert normalise([0.0, 0.0]) == [0.0, 0.0]
