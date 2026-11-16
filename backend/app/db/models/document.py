"""SOP documents and their sections ("chunks"), searchable with Postgres full-text search.

A chunk is one SOP section, so a search hit maps 1:1 to an evidence ID `sop:<slug>#<section>`
(sections are short: a test keeps every one under 800 characters, so no further splitting).
Phase 10 adds an optional pgvector `embedding` per chunk and a cache of query embeddings, used
by hybrid retrieval (services/sops/hybrid.py).
"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.common import CreatedAt, UUIDPrimaryKey

EMBEDDING_DIMENSIONS = 768


class Document(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("slug", "version", name="uq_documents_slug_version"),)

    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentChunk.position"
    )


class DocumentChunk(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "section_id", name="uq_document_chunks_doc_section"),
        Index("ix_document_chunks_tsv", "tsv", postgresql_using="gin"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[str] = mapped_column(String(10), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Title words weigh more than body words (setweight A vs B).
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(text, '')), 'B')",
            persisted=True,
        ),
        nullable=False,
    )

    # Optional semantic vector (Phase 10); NULL until scripts/embed_sops.py has run.
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(60), nullable=True)

    document: Mapped[Document] = relationship(back_populates="chunks")


class QueryEmbedding(UUIDPrimaryKey, CreatedAt, Base):
    """Cache of search-query embeddings: repeated runs cost no quota and rank identically."""

    __tablename__ = "query_embeddings"
    __table_args__ = (
        UniqueConstraint("query_hash", "model", name="uq_query_embeddings_hash_model"),
    )

    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(60), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
