"""Loading SOP files into Postgres and lexical (full-text) search over their sections."""

import re
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy import and_, func, literal_column, select
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentChunk
from app.domain.sop_corpus import SopDocumentText
from app.domain.taxonomy import sop_evidence_id

MAX_QUERY_TERMS = 16
MAX_TOP_K = 5


@dataclass(frozen=True)
class SopHit:
    evidence_id: str
    document_slug: str
    document_title: str
    section_id: str
    section_title: str
    text: str
    score: float


class SopSearcher(Protocol):
    def search(self, query: str, allowed_slugs: frozenset[str], top_k: int) -> list[SopHit]: ...


def query_terms(query: str) -> list[str]:
    """Lower-cased alphanumeric words (unique, in order). Safe to splice into to_tsquery."""
    seen: dict[str, None] = {}
    for word in re.findall(r"[a-z0-9]+", query.lower()):
        if len(word) >= 2:
            seen.setdefault(word, None)
    return list(seen)[:MAX_QUERY_TERMS]


class PostgresSopSearcher:
    """Ranks sections by ts_rank_cd over title (weight A) and body (weight B), OR-ing terms."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def search(self, query: str, allowed_slugs: frozenset[str], top_k: int = 3) -> list[SopHit]:
        terms = query_terms(query)
        if not terms or not allowed_slugs:
            return []
        tsquery = func.to_tsquery(literal_column("'english'"), " | ".join(terms))
        latest = (
            select(Document.slug, func.max(Document.version).label("version"))
            .where(Document.slug.in_(allowed_slugs))
            .group_by(Document.slug)
            .subquery()
        )
        rank = func.ts_rank_cd(DocumentChunk.tsv, tsquery).label("rank")
        rows = self.db.execute(
            select(DocumentChunk, Document.slug, Document.title, rank)
            .join(Document, DocumentChunk.document_id == Document.id)
            .join(
                latest, and_(Document.slug == latest.c.slug, Document.version == latest.c.version)
            )
            .where(DocumentChunk.tsv.op("@@")(tsquery))
            .order_by(rank.desc(), Document.slug, DocumentChunk.position)
            .limit(max(1, min(top_k, MAX_TOP_K)))
        ).all()
        return [
            SopHit(
                evidence_id=sop_evidence_id(slug, chunk.section_id),
                document_slug=slug,
                document_title=title,
                section_id=chunk.section_id,
                section_title=chunk.title,
                text=chunk.text,
                score=round(float(score), 4),
            )
            for chunk, slug, title, score in rows
        ]


SyncOutcome = Literal["created", "updated", "unchanged"]


def sync_corpus(db: Session, corpus: list[SopDocumentText]) -> list[tuple[str, int, SyncOutcome]]:
    """Upserts each SOP (keyed by slug + version) and its sections. Idempotent."""
    results: list[tuple[str, int, SyncOutcome]] = []
    for doc in corpus:
        row = db.scalar(
            select(Document).where(Document.slug == doc.slug, Document.version == doc.version)
        )
        if row is not None and row.content_hash == doc.content_hash:
            results.append((doc.slug, doc.version, "unchanged"))
            continue
        outcome: SyncOutcome = "created" if row is None else "updated"
        if row is None:
            row = Document(slug=doc.slug, version=doc.version)
            db.add(row)
        row.title = doc.title
        row.document_type = doc.document_type
        row.content = doc.content
        row.content_hash = doc.content_hash
        row.metadata_json = {"source": f"data/sops/{doc.slug}.md"}
        row.chunks.clear()
        db.flush()  # delete old chunks before inserting sections with the same IDs
        row.chunks.extend(
            DocumentChunk(section_id=s.id, position=i, title=s.title, text=s.text)
            for i, s in enumerate(doc.sections, start=1)
        )
        results.append((doc.slug, doc.version, outcome))
    db.commit()
    return results
