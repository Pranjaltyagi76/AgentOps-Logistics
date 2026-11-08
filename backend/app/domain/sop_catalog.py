"""Registry of synthetic SOP documents and their section IDs (data/sops/catalog.json).

Scenarios reference SOP evidence as `sop:<slug>#<section>`; validation checks those against
this catalog. The section text itself lives in data/sops/<slug>.md (Phase 2).
"""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel


class SopSection(BaseModel):
    id: str
    title: str


class SopDocument(BaseModel):
    slug: str
    title: str
    document_type: str
    sections: list[SopSection]

    @property
    def section_ids(self) -> set[str]:
        return {section.id for section in self.sections}


class SopCatalog(BaseModel):
    catalog_version: str
    documents: list[SopDocument]

    def get(self, slug: str) -> SopDocument | None:
        return next((doc for doc in self.documents if doc.slug == slug), None)

    @property
    def slugs(self) -> set[str]:
        return {doc.slug for doc in self.documents}


def load_catalog(path: Path) -> SopCatalog:
    return SopCatalog.model_validate(json.loads(path.read_text(encoding="utf-8")))


@lru_cache
def get_catalog(data_dir: Path) -> SopCatalog:
    return load_catalog(data_dir / "sops" / "catalog.json")
