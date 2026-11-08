"""Scenario catalog endpoints. Reads need any session; writes need the owner role."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import OwnerDep, Principal, PrincipalDep, SettingsDep
from app.db.models import Scenario
from app.db.session import get_db
from app.domain.sop_catalog import get_catalog
from app.domain.taxonomy import Category, Difficulty, ScenarioStatus
from app.schemas.scenario import ScenarioSpec
from app.schemas.scenario_api import (
    CloneIn,
    ExportOut,
    ImportIn,
    ImportItemOut,
    ImportOut,
    ScenarioDetailOut,
    ScenarioPageOut,
    ScenarioSummaryOut,
    ScenarioVersionOut,
    ScenarioWriteIn,
    ScenarioWriteOut,
    StatusChangeOut,
    ValidateOut,
)
from app.services.scenarios.service import ListFilters, ScenarioService, canonical_json

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


def get_service(settings: SettingsDep, db: Annotated[Session, Depends(get_db)]) -> ScenarioService:
    return ScenarioService(db, get_catalog(settings.data_dir))


ServiceDep = Annotated[ScenarioService, Depends(get_service)]


def _summary(row: Scenario) -> ScenarioSummaryOut:
    return ScenarioSummaryOut(
        id=row.id,
        scenario_key=row.scenario_key,
        version=row.version,
        title=row.title,
        category=row.category,
        difficulty=row.difficulty,
        status=row.status,
        tags=list(row.tags),
        is_locked=row.is_locked,
        updated_at=row.updated_at,
    )


def _mask_name(name: str) -> str:
    return " ".join(part[0] + "*" * (len(part) - 1) for part in name.split() if part)


def _redact_people(visible: dict[str, Any]) -> dict[str, Any]:
    """Masks recipient names for viewers (data is synthetic; this demonstrates NFR-06)."""
    for shipment in visible.get("mock_data", {}).get("shipments", []):
        if shipment.get("recipient_name"):
            shipment["recipient_name"] = _mask_name(shipment["recipient_name"])
    return visible


def _detail(service: ScenarioService, row: Scenario, principal: Principal) -> ScenarioDetailOut:
    spec = ScenarioSpec.model_validate(row.scenario_json)
    hidden: dict[str, Any] | None = None
    if principal.is_owner:
        hidden = {
            key: row.scenario_json.get(key)
            for key in ("ground_truth", "evaluation", "fault_injection", "author_note")
        }
    versions = service.versions(row.scenario_key)
    return ScenarioDetailOut(
        **_summary(row).model_dump(),
        created_at=row.created_at,
        versions=[
            ScenarioVersionOut(
                id=v.id,
                version=v.version,
                status=v.status,
                is_locked=v.is_locked,
                created_at=v.created_at,
            )
            for v in versions
        ],
        visible=spec.visible_view() if principal.is_owner else _redact_people(spec.visible_view()),
        hidden=hidden,
        can_edit=principal.is_owner and versions[0].id == row.id,
    )


@router.get("", response_model=ScenarioPageOut)
def list_scenarios(
    service: ServiceDep,
    _: PrincipalDep,
    category: Category | None = None,
    difficulty: Difficulty | None = None,
    status: ScenarioStatus | None = None,
    tag: Annotated[str | None, Query(max_length=40)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> ScenarioPageOut:
    filters = ListFilters(
        category=category, difficulty=difficulty, status=status, tag=tag, q=q or None
    )
    rows, next_cursor, total = service.list_page(filters, limit=limit, cursor=cursor)
    return ScenarioPageOut(items=[_summary(r) for r in rows], next_cursor=next_cursor, total=total)


@router.post("/validate", response_model=ValidateOut)
def validate_scenario(
    service: ServiceDep, _: PrincipalDep, scenario: Annotated[dict[str, Any], Body()]
) -> ValidateOut:
    _, report = service.validate(scenario)
    return report


@router.post("/import", response_model=ImportOut)
def import_scenarios(service: ServiceDep, _: OwnerDep, body: ImportIn) -> ImportOut:
    results = [ImportItemOut(**r.__dict__) for r in service.import_many(body.scenarios)]
    counts = {
        o: sum(1 for r in results if r.outcome == o)
        for o in ("created", "updated", "unchanged", "error")
    }
    return ImportOut(
        results=results,
        created=counts["created"],
        updated=counts["updated"],
        unchanged=counts["unchanged"],
        errors=counts["error"],
    )


@router.get("/export", response_model=ExportOut)
def export_scenarios(service: ServiceDep, _: OwnerDep) -> ExportOut:
    return ExportOut(exported_at=datetime.now(UTC), scenarios=service.export_latest())


@router.post("", response_model=ScenarioWriteOut, status_code=201)
def create_scenario(
    service: ServiceDep, principal: OwnerDep, body: ScenarioWriteIn
) -> ScenarioWriteOut:
    row = service.create(body.scenario, status=body.status or ScenarioStatus.ACTIVE)
    _, report = service.validate(body.scenario)
    return ScenarioWriteOut(
        outcome="created",
        scenario=_detail(service, row, principal),
        warnings=[w.model_dump() for w in report.warnings],
    )


@router.get("/{scenario_id}", response_model=ScenarioDetailOut)
def get_scenario(
    service: ServiceDep, principal: PrincipalDep, scenario_id: uuid.UUID
) -> ScenarioDetailOut:
    return _detail(service, service.get(scenario_id), principal)


@router.patch("/{scenario_id}", response_model=ScenarioWriteOut)
def update_scenario(
    service: ServiceDep,
    principal: OwnerDep,
    scenario_id: uuid.UUID,
    body: ScenarioWriteIn,
    response: Response,
) -> ScenarioWriteOut:
    row, outcome = service.update(scenario_id, body.scenario, status=body.status)
    if outcome == "new_version":
        response.status_code = 201
    _, report = service.validate({**row.scenario_json})
    return ScenarioWriteOut(
        outcome=outcome,
        scenario=_detail(service, row, principal),
        warnings=[w.model_dump() for w in report.warnings],
    )


@router.post("/{scenario_id}/clone", response_model=ScenarioWriteOut, status_code=201)
def clone_scenario(
    service: ServiceDep,
    principal: OwnerDep,
    scenario_id: uuid.UUID,
    body: Annotated[CloneIn | None, Body()] = None,
) -> ScenarioWriteOut:
    row = service.clone(scenario_id, body.new_scenario_id if body else None)
    return ScenarioWriteOut(outcome="created", scenario=_detail(service, row, principal))


@router.post("/{scenario_id}/archive", response_model=StatusChangeOut)
def archive_scenario(service: ServiceDep, _: OwnerDep, scenario_id: uuid.UUID) -> StatusChangeOut:
    rows = service.set_status(scenario_id, ScenarioStatus.ARCHIVED)
    return StatusChangeOut(
        scenario_key=rows[0].scenario_key,
        status=ScenarioStatus.ARCHIVED,
        versions_changed=len(rows),
    )


@router.post("/{scenario_id}/restore", response_model=StatusChangeOut)
def restore_scenario(service: ServiceDep, _: OwnerDep, scenario_id: uuid.UUID) -> StatusChangeOut:
    rows = service.set_status(scenario_id, ScenarioStatus.ACTIVE)
    return StatusChangeOut(
        scenario_key=rows[0].scenario_key, status=ScenarioStatus.ACTIVE, versions_changed=len(rows)
    )


@router.get("/{scenario_id}/export")
def export_scenario(service: ServiceDep, _: OwnerDep, scenario_id: uuid.UUID) -> JSONResponse:
    row = service.get(scenario_id)
    filename = f"{row.scenario_key}.v{row.version}.json"
    return JSONResponse(
        content=canonical_json(row),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
