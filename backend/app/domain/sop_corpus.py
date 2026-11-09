"""Parses the synthetic SOP documents in data/sops/<slug>.md.

File format:

    ---
    slug: delay-communication
    title: Delay Communication Policy
    document_type: policy
    version: 1
    ---

    ## s1. Section title
    Section text ...

Each `## sN. Title` heading starts a section whose ID is part of the evidence ID
`sop:<slug>#sN`. `check_against_catalog` keeps the files and data/sops/catalog.json in step.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from app.domain.sop_catalog import SopCatalog

_FRONT_MATTER = re.compile(r"\A---\n(?P<meta>.*?)\n---\n(?P<body>.*)\Z", re.DOTALL)
_SECTION_HEADING = re.compile(r"^## (?P<id>s\d{1,2})\. (?P<title>.+)$", re.MULTILINE)
_REQUIRED_META = ("slug", "title", "document_type", "version")


class SopFormatError(ValueError):
    pass


@dataclass(frozen=True)
class SopSectionText:
    id: str
    title: str
    text: str


@dataclass(frozen=True)
class SopDocumentText:
    slug: str
    title: str
    document_type: str
    version: int
    sections: tuple[SopSectionText, ...]
    content: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


def parse_sop(text: str, *, source: str = "<sop>") -> SopDocumentText:
    text = text.replace("\r\n", "\n")
    match = _FRONT_MATTER.match(text)
    if not match:
        raise SopFormatError(f"{source}: missing '---' front matter")
    meta: dict[str, str] = {}
    for line in match["meta"].splitlines():
        if line.strip():
            key, sep, value = line.partition(":")
            if not sep:
                raise SopFormatError(f"{source}: bad front matter line {line!r}")
            meta[key.strip()] = value.strip()
    missing = [key for key in _REQUIRED_META if not meta.get(key)]
    if missing:
        raise SopFormatError(f"{source}: front matter is missing {', '.join(missing)}")
    if not meta["version"].isdigit():
        raise SopFormatError(f"{source}: version must be a positive integer")

    body = match["body"]
    headings = list(_SECTION_HEADING.finditer(body))
    if not headings:
        raise SopFormatError(f"{source}: no '## sN. Title' sections found")
    sections: list[SopSectionText] = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        section_text = " ".join(body[heading.end() : end].split())
        if not section_text:
            raise SopFormatError(f"{source}: section {heading['id']} is empty")
        sections.append(SopSectionText(heading["id"], heading["title"].strip(), section_text))
    ids = [section.id for section in sections]
    if len(ids) != len(set(ids)):
        raise SopFormatError(f"{source}: duplicate section IDs")

    return SopDocumentText(
        slug=meta["slug"],
        title=meta["title"],
        document_type=meta["document_type"],
        version=int(meta["version"]),
        sections=tuple(sections),
        content=body.strip(),
    )


def load_corpus(sops_dir: Path) -> list[SopDocumentText]:
    documents = []
    for path in sorted(sops_dir.glob("*.md")):
        document = parse_sop(path.read_text(encoding="utf-8"), source=path.name)
        if path.stem != document.slug:
            raise SopFormatError(f"{path.name}: file name must be {document.slug}.md")
        documents.append(document)
    return documents


def check_against_catalog(corpus: list[SopDocumentText], catalog: SopCatalog) -> list[str]:
    """Returns human-readable mismatches between the SOP files and catalog.json."""
    problems: list[str] = []
    by_slug = {doc.slug: doc for doc in corpus}
    for entry in catalog.documents:
        doc = by_slug.get(entry.slug)
        if doc is None:
            problems.append(f"catalog document '{entry.slug}' has no {entry.slug}.md file")
            continue
        if doc.title != entry.title:
            problems.append(f"{entry.slug}: title {doc.title!r} != catalog {entry.title!r}")
        file_sections = {s.id: s.title for s in doc.sections}
        catalog_sections = {s.id: s.title for s in entry.sections}
        if file_sections != catalog_sections:
            problems.append(f"{entry.slug}: sections {file_sections} != catalog {catalog_sections}")
    for slug in by_slug.keys() - catalog.slugs:
        problems.append(f"{slug}.md is not listed in catalog.json")
    return problems
