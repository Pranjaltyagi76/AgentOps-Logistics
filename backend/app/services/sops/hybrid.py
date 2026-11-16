"""Hybrid SOP retrieval: full-text and vector rankings fused with reciprocal rank fusion (RRF).

Used when SOP_RETRIEVAL=hybrid and the permitted sections have embeddings; otherwise it falls
back to the lexical ranking, so a server without embeddings (or without a Gemini key) behaves
exactly like lexical-v1. Query embeddings are cached in `query_embeddings`, so repeating a
benchmark costs no quota and ranks identically.

RRF score of a section = sum over the two rankings of 1 / (K + rank), K = 60. Sections found
by only one ranking still count. Ties break by evidence ID, so the order is deterministic.
"""

import hashlib
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import replace
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Document, DocumentChunk, QueryEmbedding
from app.domain.taxonomy import sop_evidence_id
from app.services.sops.embeddings import Embedder, GeminiEmbedder, chunk_text
from app.services.sops.service import (
    MAX_TOP_K,
    PerCallSopSearcher,
    PostgresSopSearcher,
    SopHit,
    SopSearcher,
    query_terms,
)

logger = logging.getLogger(__name__)

RRF_K = 60
CANDIDATES = 10
LEXICAL_VERSION = "lexical-v1"
HYBRID_VERSION = "hybrid-v1"


def query_hash(query: str) -> str:
    return hashlib.sha256(" ".join(query.lower().split()).encode()).hexdigest()


class HybridSopSearcher:
    def __init__(self, db: Session, embedder: Embedder) -> None:
        self.db = db
        self.embedder = embedder
        self.lexical = PostgresSopSearcher(db)
        self.last_mode = LEXICAL_VERSION  # what the most recent search actually used

    def _latest(self, allowed_slugs: frozenset[str]) -> Any:
        return (
            select(Document.slug, func.max(Document.version).label("version"))
            .where(Document.slug.in_(allowed_slugs))
            .group_by(Document.slug)
            .subquery()
        )

    def _query_vector(self, query: str) -> list[float]:
        key = query_hash(query)
        cached = self.db.scalar(
            select(QueryEmbedding.embedding).where(
                QueryEmbedding.query_hash == key, QueryEmbedding.model == self.embedder.model
            )
        )
        if cached is not None:
            return list(cached)
        vector = self.embedder.embed([query], "query")[0]
        self.db.execute(
            insert(QueryEmbedding)
            .values(query_hash=key, model=self.embedder.model, query_text=query, embedding=vector)
            .on_conflict_do_nothing(constraint="uq_query_embeddings_hash_model")
        )
        self.db.commit()
        return vector

    def _vector_hits(self, query: str, allowed_slugs: frozenset[str]) -> list[SopHit] | None:
        latest = self._latest(allowed_slugs)
        joined = (
            select(DocumentChunk, Document.slug, Document.title)
            .join(Document, DocumentChunk.document_id == Document.id)
            .join(
                latest, and_(Document.slug == latest.c.slug, Document.version == latest.c.version)
            )
        )
        embedded = self.db.scalar(
            select(func.count()).select_from(
                joined.where(DocumentChunk.embedding_model == self.embedder.model).subquery()
            )
        )
        if not embedded:
            return None  # nothing embedded with this model: fall back to lexical
        vector = self._query_vector(query)
        distance = DocumentChunk.embedding.cosine_distance(vector)
        rows = self.db.execute(
            joined.add_columns(distance.label("distance"))
            .where(DocumentChunk.embedding_model == self.embedder.model)
            .order_by(distance, Document.slug, DocumentChunk.position)
            .limit(CANDIDATES)
        ).all()
        return [
            SopHit(
                evidence_id=sop_evidence_id(slug, chunk.section_id),
                document_slug=slug,
                document_title=title,
                section_id=chunk.section_id,
                section_title=chunk.title,
                text=chunk.text,
                score=round(1 - float(dist), 4),
            )
            for chunk, slug, title, dist in rows
        ]

    def search(self, query: str, allowed_slugs: frozenset[str], top_k: int = 3) -> list[SopHit]:
        top_k = max(1, min(top_k, MAX_TOP_K))
        if not allowed_slugs or not query_terms(query):
            self.last_mode = LEXICAL_VERSION
            return []  # same contract as text search: nothing permitted or nothing to search for
        lexical = self.lexical.search(query, allowed_slugs, CANDIDATES)
        try:
            vector = self._vector_hits(query, allowed_slugs)
        except Exception:  # embedding provider down: degrade to lexical, never fail the run
            logger.warning("Hybrid SOP search fell back to lexical", exc_info=True)
            self.db.rollback()
            vector = None
        if vector is None:
            self.last_mode = LEXICAL_VERSION
            return lexical[:top_k]
        self.last_mode = HYBRID_VERSION
        scores: dict[str, float] = {}
        hits: dict[str, SopHit] = {}
        for ranking in (lexical, vector):
            for rank, hit in enumerate(ranking, start=1):
                scores[hit.evidence_id] = scores.get(hit.evidence_id, 0.0) + 1 / (RRF_K + rank)
                hits.setdefault(hit.evidence_id, hit)
        order = sorted(scores, key=lambda e: (-scores[e], e))
        return [replace(hits[e], score=round(scores[e], 6)) for e in order[:top_k]]


class PerCallHybridSearcher:
    """Hybrid searcher that opens a short session per search (like PerCallSopSearcher)."""

    def __init__(
        self, session_factory: Callable[[], AbstractContextManager[Session]], embedder: Embedder
    ) -> None:
        self.session_factory = session_factory
        self.embedder = embedder

    def search(self, query: str, allowed_slugs: frozenset[str], top_k: int = 3) -> list[SopHit]:
        with self.session_factory() as db:
            return HybridSopSearcher(db, self.embedder).search(query, allowed_slugs, top_k)


def gemini_embedder(settings: Settings) -> Embedder | None:
    if settings.gemini_api_key is None:
        return None
    from app.services.providers.factory import gemini_client

    client = gemini_client(settings.gemini_api_key.get_secret_value())
    return GeminiEmbedder(client, settings.embedding_model)


def retrieval_version(settings: Settings, db: Session) -> str:
    """The retrieval mode a new run will use, recorded in `runs.versions_json["retrieval"]`."""
    if settings.sop_retrieval != "hybrid" or settings.gemini_api_key is None:
        return LEXICAL_VERSION
    embedded = db.scalar(
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.embedding_model == settings.embedding_model)
    )
    return HYBRID_VERSION if embedded else LEXICAL_VERSION


def build_sop_searcher(
    settings: Settings,
    session_factory: Callable[[], AbstractContextManager[Session]],
    embedder: Embedder | None = None,
) -> SopSearcher:
    if settings.sop_retrieval == "hybrid":
        embedder = embedder or gemini_embedder(settings)
        if embedder is not None:
            return PerCallHybridSearcher(session_factory, embedder)
    return PerCallSopSearcher(session_factory)


def embed_corpus(
    db: Session, embedder: Embedder, *, batch_size: int = 50, dry_run: bool = False
) -> int:
    """Embeds every SOP section whose stored embedding is missing or from another model.

    Returns the number of sections that needed it. One provider request per batch, so the
    current 12-document corpus (~45 sections) costs one embedding request.
    """
    rows = db.execute(
        select(DocumentChunk, Document.title)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(
            DocumentChunk.embedding.is_(None)
            | (DocumentChunk.embedding_model != embedder.model)
            | DocumentChunk.embedding_model.is_(None)
        )
        .order_by(Document.slug, Document.version, DocumentChunk.position)
    ).all()
    if dry_run or not rows:
        return len(rows)
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        texts = [chunk_text(title, chunk.title, chunk.text) for chunk, title in batch]
        vectors = embedder.embed(texts, "document")
        if len(vectors) != len(batch):
            raise RuntimeError(f"Embedder returned {len(vectors)} vectors for {len(batch)} texts")
        for (chunk, _), vector in zip(batch, vectors, strict=True):
            chunk.embedding = vector
            chunk.embedding_model = embedder.model
        db.commit()
    return len(rows)
