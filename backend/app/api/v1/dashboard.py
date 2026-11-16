"""Dashboard summary and report exports (FR-09, FR-10). Read-only; any signed-in principal."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import PrincipalDep
from app.core.errors import AppError
from app.db.models import Run, SuiteRun
from app.db.session import get_db
from app.services.dashboard.service import summary
from app.services.reports.service import (
    run_report,
    run_report_csv,
    suite_report,
    suite_report_csv,
)

router = APIRouter(tags=["dashboard", "reports"])
DbDep = Annotated[Session, Depends(get_db)]
Format = Literal["json", "csv"]


class KpiOut(BaseModel):
    key: str
    label: str
    unit: Literal["count", "rate", "score", "ms", "usd"]
    value: float | None  # None = unknown (nothing to measure)
    definition: str
    sql: str


class FailureTypeOut(BaseModel):
    failure_type: str
    items: int
    main_findings: int
    runs: int


class AgentVersionOut(BaseModel):
    agent_name: str
    agent_version: int
    provider: str
    runs: int
    pass_rate: float | None
    mean_score: float | None
    policy_violation_rate: float | None
    mean_latency_ms: float | None


class RecentRunOut(BaseModel):
    id: uuid.UUID
    scenario_key: str
    scenario_version: int
    agent_name: str
    agent_version: int
    provider: str
    status: str
    verdict: str | None
    score: float | None
    is_demo: bool
    created_at: datetime


class RecentSuiteRunOut(BaseModel):
    id: uuid.UUID
    suite_name: str
    agent_name: str
    agent_version: int
    status: str
    total_runs: int
    is_demo: bool
    created_at: datetime
    task_success_rate: float | None


class DashboardOut(BaseModel):
    version: str
    include_demo: bool
    demo_runs: int
    kpis: list[KpiOut]
    failure_types: list[FailureTypeOut]
    agent_versions: list[AgentVersionOut]
    recent_runs: list[RecentRunOut]
    recent_suite_runs: list[RecentSuiteRunOut]
    queries: dict[str, str]


@router.get("/dashboard/summary", response_model=DashboardOut)
def dashboard_summary(db: DbDep, _: PrincipalDep, include_demo: bool = True) -> dict[str, Any]:
    """KPIs, failure types, agent versions and recent activity; each KPI carries its SQL."""
    return summary(db, include_demo=include_demo)


def _export(document: dict[str, Any], csv_text: str, fmt: Format, filename: str) -> Response:
    if fmt == "csv":
        return Response(
            csv_text,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )
    return JSONResponse(
        document, headers={"Content-Disposition": f'inline; filename="{filename}.json"'}
    )


@router.get("/reports/runs/{run_id}")
def export_run_report(
    db: DbDep,
    principal: PrincipalDep,
    run_id: uuid.UUID,
    format: Annotated[Format, Query()] = "json",
) -> Response:
    run = db.get(Run, run_id)
    if run is None:
        raise AppError("Run not found", code="run_not_found", status_code=404)
    report = run_report(db, run, owner=principal.is_owner)
    return _export(report, run_report_csv(report), format, f"run-{run_id}")


@router.get("/reports/suite-runs/{suite_run_id}")
def export_suite_report(
    db: DbDep,
    principal: PrincipalDep,
    suite_run_id: uuid.UUID,
    format: Annotated[Format, Query()] = "json",
) -> Response:
    suite_run = db.get(SuiteRun, suite_run_id)
    if suite_run is None:
        raise AppError("Suite run not found", code="suite_run_not_found", status_code=404)
    report = suite_report(db, suite_run, owner=principal.is_owner)
    return _export(
        report, suite_report_csv(report), format, f"benchmark-{suite_run.suite_name}-{suite_run_id}"
    )
