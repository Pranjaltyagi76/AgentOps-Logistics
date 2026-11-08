"""Public, read-only vocabularies for the UI and the scenario editor."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.domain.sop_catalog import get_catalog
from app.domain.taxonomy import taxonomy_payload

router = APIRouter(tags=["taxonomy"])


@router.get("/taxonomy")
def get_taxonomy(settings: SettingsDep) -> dict[str, Any]:
    catalog = get_catalog(settings.data_dir)
    return {
        **taxonomy_payload(),
        "sop_documents": [
            {"slug": d.slug, "title": d.title, "sections": [s.model_dump() for s in d.sections]}
            for d in catalog.documents
        ],
    }
