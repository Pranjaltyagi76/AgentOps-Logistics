import pytest

from app.core.config import DEFAULT_DATA_DIR
from app.domain.sop_catalog import SopCatalog
from app.domain.sop_corpus import SopFormatError, check_against_catalog, load_corpus, parse_sop
from app.services.sops.service import query_terms

GOOD = """---
slug: demo
title: Demo Policy
document_type: policy
version: 2
---

## s1. First
Line one
line two.

## s2. Second
Text.
"""


def test_corpus_files_match_the_catalog(catalog: SopCatalog) -> None:
    corpus = load_corpus(DEFAULT_DATA_DIR / "sops")
    assert len(corpus) == len(catalog.documents) == 7
    assert check_against_catalog(corpus, catalog) == []


def test_parse_sop_sections_and_metadata() -> None:
    doc = parse_sop(GOOD)
    assert (doc.slug, doc.title, doc.version) == ("demo", "Demo Policy", 2)
    assert [(s.id, s.title, s.text) for s in doc.sections] == [
        ("s1", "First", "Line one line two."),
        ("s2", "Second", "Text."),
    ]
    assert len(doc.content_hash) == 64
    assert parse_sop(GOOD.replace("\n", "\r\n")).content_hash == doc.content_hash


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("## s1. No front matter\ntext", "front matter"),
        (GOOD.replace("version: 2\n", ""), "missing version"),
        (GOOD.replace("version: 2", "version: two"), "positive integer"),
        (GOOD.replace("Text.\n", ""), "s2 is empty"),
        (GOOD.replace("## s2. Second", "## s1. Again"), "duplicate section"),
        (GOOD.split("## s1")[0], "no '## sN. Title' sections"),
    ],
)
def test_parse_sop_rejects_bad_files(text: str, error: str) -> None:
    with pytest.raises(SopFormatError, match=error):
        parse_sop(text)


def test_catalog_mismatches_are_reported(catalog: SopCatalog) -> None:
    corpus = [doc for doc in load_corpus(DEFAULT_DATA_DIR / "sops") if doc.slug != "data-quality"]
    corpus.append(parse_sop(GOOD))
    problems = check_against_catalog(corpus, catalog)
    assert any("data-quality" in p and "no data-quality.md" in p for p in problems)
    assert any("demo.md is not listed" in p for p in problems)


def test_query_terms_are_sanitised() -> None:
    assert query_terms("ETA? Exact date!! date; DROP TABLE x' | a") == [
        "eta",
        "exact",
        "date",
        "drop",
        "table",
    ]
    assert query_terms("!!") == []
