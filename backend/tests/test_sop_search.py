"""Postgres full-text SOP search and corpus syncing (needs a database)."""

import dataclasses
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import DEFAULT_DATA_DIR
from app.db.models import DocumentChunk
from app.domain.sop_catalog import SopCatalog
from app.domain.sop_corpus import load_corpus
from app.domain.taxonomy import EVIDENCE_PATTERNS
from app.services.sops.service import PostgresSopSearcher, sync_corpus

pytestmark = pytest.mark.db

ALL_SLUGS = frozenset(
    {
        "delay-communication",
        "failed-delivery",
        "escalation-sla",
        "refund-reroute",
        "carrier-integration",
        "data-quality",
        "response-templates",
    }
)


@pytest.fixture
def searcher(db_session: Session) -> PostgresSopSearcher:
    sync_corpus(db_session, load_corpus(DEFAULT_DATA_DIR / "sops"))
    return PostgresSopSearcher(db_session)


def test_sync_is_idempotent_and_updates_changed_documents(db_session: Session) -> None:
    corpus = load_corpus(DEFAULT_DATA_DIR / "sops")
    assert {o for *_, o in sync_corpus(db_session, corpus)} == {"created"}
    assert {o for *_, o in sync_corpus(db_session, corpus)} == {"unchanged"}
    sections = sum(len(d.sections) for d in corpus)
    assert db_session.scalar(select(func.count()).select_from(DocumentChunk)) == sections

    changed = dataclasses.replace(corpus[0], content=corpus[0].content + "\nEdited.")
    results = sync_corpus(db_session, [changed])
    assert results == [(changed.slug, changed.version, "updated")]
    assert db_session.scalar(select(func.count()).select_from(DocumentChunk)) == sections


@pytest.mark.parametrize(
    ("query", "expected_top"),
    [
        (
            "customer wants an exact delivery date but the ETA is recalculating",
            "sop:delay-communication#s3",
        ),
        ("customer demands a refund", "sop:refund-reroute#s2"),
        ("carrier API timed out", "sop:carrier-integration#s2"),
        ("tracking event dated in the future", "sop:data-quality#s2"),
        ("redelivery after a failed attempt", "sop:failed-delivery#s3"),
        ("express SLA breached", "sop:escalation-sla#s2"),
        ("deliver to my office address instead", "sop:failed-delivery#s4"),
    ],
)
def test_natural_queries_rank_the_right_section_first(
    searcher: PostgresSopSearcher, query: str, expected_top: str
) -> None:
    hits = searcher.search(query, ALL_SLUGS, 3)
    assert hits and hits[0].evidence_id == expected_top, [h.evidence_id for h in hits]
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_search_never_returns_documents_outside_the_allowed_set(
    searcher: PostgresSopSearcher,
) -> None:
    hits = searcher.search("customer demands a refund", frozenset({"delay-communication"}), 5)
    assert hits and {h.document_slug for h in hits} == {"delay-communication"}
    assert searcher.search("refund", frozenset(), 3) == []
    assert searcher.search("!!! ??", ALL_SLUGS, 3) == []


def test_every_required_sop_section_is_findable_by_its_title(
    searcher: PostgresSopSearcher, scenario_files: dict[str, dict[str, Any]], catalog: SopCatalog
) -> None:
    for name, data in scenario_files.items():
        allowed = frozenset(data["permitted_documents"])
        for evidence_id in data["ground_truth"]["required_evidence"]:
            match = EVIDENCE_PATTERNS["sop"].match(evidence_id)
            if not match:
                continue
            doc = catalog.get(match["doc"])
            assert doc is not None
            title = next(s.title for s in doc.sections if s.id == match["section"])
            found = [h.evidence_id for h in searcher.search(title, allowed, 3)]
            assert evidence_id in found, (name, evidence_id, found)
