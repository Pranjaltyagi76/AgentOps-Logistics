"""Benchmark suites, suite runs and regression comparisons (FR-08).

Reads need any session; suite edits need the owner. Anyone can launch a suite with a
rule-based agent; LLM suites are owner-only and take their whole daily allowance up front.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import OwnerDep, PrincipalDep, SettingsDep
from app.db.models import BenchmarkSuite, SuiteRun
from app.db.session import get_db
from app.domain.metrics import RunResult
from app.services.benchmarks.service import MAX_REPEATS, SuiteService, SuiteSpec
from app.services.execution.service import RunService

router = APIRouter(tags=["benchmarks"])


def get_service(
    request: Request, settings: SettingsDep, db: Annotated[Session, Depends(get_db)]
) -> SuiteService:
    state = request.app.state
    runs = RunService(db, settings, state.executor, state.session_factory, state.run_limiter)
    return SuiteService(db, runs)


ServiceDep = Annotated[SuiteService, Depends(get_service)]


# --- suites ----------------------------------------------------------------------------------


class SuiteOut(BaseModel):
    id: uuid.UUID
    name: str
    title: str
    description: str
    status: str
    tag: str | None
    scenario_keys: list[str] | None
    pinned_versions: dict[str, int]
    resolved: list[dict[str, Any]]  # what a run would use right now
    resolve_problem: str | None
    created_at: datetime
    updated_at: datetime


def _suite_out(service: SuiteService, suite: BenchmarkSuite) -> SuiteOut:
    spec = service.spec_of(suite)
    try:
        resolved = [
            {
                "scenario_key": s.scenario_key,
                "version": s.version,
                "title": s.title,
                "category": s.category,
            }
            for s in service.resolve(suite)
        ]
        problem = None
    except Exception as exc:  # shown, not raised: the suite can still be edited
        resolved, problem = [], str(exc)
    return SuiteOut(
        id=suite.id,
        name=suite.name,
        title=suite.title,
        description=suite.description,
        status=suite.status,
        tag=suite.tag_filter,
        scenario_keys=spec.scenario_keys,
        pinned_versions=spec.pinned_versions,
        resolved=resolved,
        resolve_problem=problem,
        created_at=suite.created_at,
        updated_at=suite.updated_at,
    )


@router.get("/suites", response_model=list[SuiteOut])
def list_suites(
    service: ServiceDep, _: PrincipalDep, include_archived: bool = False
) -> list[SuiteOut]:
    return [_suite_out(service, s) for s in service.list_suites(include_archived)]


@router.post("/suites", response_model=SuiteOut, status_code=201)
def create_suite(service: ServiceDep, _: OwnerDep, spec: SuiteSpec) -> SuiteOut:
    return _suite_out(service, service.create(spec))


@router.get("/suites/{suite_id}", response_model=SuiteOut)
def get_suite(service: ServiceDep, _: PrincipalDep, suite_id: uuid.UUID) -> SuiteOut:
    return _suite_out(service, service.get(suite_id))


@router.put("/suites/{suite_id}", response_model=SuiteOut)
def update_suite(
    service: ServiceDep, _: OwnerDep, suite_id: uuid.UUID, spec: SuiteSpec
) -> SuiteOut:
    return _suite_out(service, service.update(suite_id, spec))


@router.post("/suites/{suite_id}/archive", response_model=SuiteOut)
def archive_suite(service: ServiceDep, _: OwnerDep, suite_id: uuid.UUID) -> SuiteOut:
    return _suite_out(service, service.set_status(suite_id, "archived"))


@router.post("/suites/{suite_id}/restore", response_model=SuiteOut)
def restore_suite(service: ServiceDep, _: OwnerDep, suite_id: uuid.UUID) -> SuiteOut:
    return _suite_out(service, service.set_status(suite_id, "active"))


# --- suite runs ------------------------------------------------------------------------------


class SuiteRunIn(BaseModel):
    agent_config_id: uuid.UUID
    repeats: int = Field(default=1, ge=1, le=MAX_REPEATS)


class SuiteRunOut(BaseModel):
    id: uuid.UUID
    suite_id: uuid.UUID
    suite_name: str
    agent_config_id: uuid.UUID
    agent_name: str
    agent_version: int
    provider: str
    status: str
    repeats: int
    total_runs: int
    progress: dict[str, int]
    scenarios: list[dict[str, Any]]
    evaluator_version: str | None
    metrics: dict[str, Any] | None
    flaky: list[str]
    cancel_requested: bool
    triggered_by_role: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SuiteRunResultOut(BaseModel):
    run_id: str
    scenario_key: str
    scenario_version: int
    repeat_index: int
    status: str
    verdict: str | None
    score: float | None
    gate_failures: list[str]
    main_failure: str | None
    latency_ms: int | None
    tokens: int | None


class SuiteRunDetailOut(SuiteRunOut):
    results: list[SuiteRunResultOut]


def _suite_run_out(service: SuiteService, row: SuiteRun) -> SuiteRunOut:
    summary = row.summary_json or {}
    return SuiteRunOut(
        id=row.id,
        suite_id=row.suite_id,
        suite_name=row.suite_name,
        agent_config_id=row.agent_config_id,
        agent_name=row.agent_name,
        agent_version=row.agent_version,
        provider=row.provider,
        status=row.status,
        repeats=row.repeats,
        total_runs=row.total_runs,
        progress=service.progress(row.id),
        scenarios=row.scenarios_json,
        evaluator_version=row.evaluator_version,
        metrics=summary.get("metrics"),
        flaky=summary.get("flaky", []),
        cancel_requested=row.cancel_requested,
        triggered_by_role=row.triggered_by_role,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _result_out(r: RunResult) -> SuiteRunResultOut:
    return SuiteRunResultOut(
        run_id=r.run_id,
        scenario_key=r.scenario_key,
        scenario_version=r.scenario_version,
        repeat_index=r.repeat_index,
        status=r.status,
        verdict=r.verdict,
        score=r.score,
        gate_failures=list(r.gate_failures),
        main_failure=r.main_failure,
        latency_ms=r.latency_ms,
        tokens=r.tokens,
    )


@router.post("/suites/{suite_id}/runs", response_model=SuiteRunOut, status_code=202)
def launch_suite_run(
    service: ServiceDep,
    principal: PrincipalDep,
    suite_id: uuid.UUID,
    body: Annotated[SuiteRunIn, Body()],
) -> SuiteRunOut:
    row = service.launch(suite_id, body.agent_config_id, body.repeats, principal)
    return _suite_run_out(service, row)


@router.get("/suite-runs", response_model=list[SuiteRunOut])
def list_suite_runs(
    service: ServiceDep,
    _: PrincipalDep,
    suite_id: uuid.UUID | None = None,
    status: Annotated[str | None, Query(pattern=r"^(queued|running|completed|cancelled)$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[SuiteRunOut]:
    rows = service.list_runs(suite_id=suite_id, status=status, limit=limit)
    return [_suite_run_out(service, r) for r in rows]


@router.get("/suite-runs/{suite_run_id}", response_model=SuiteRunDetailOut)
def get_suite_run(
    service: ServiceDep, _: PrincipalDep, suite_run_id: uuid.UUID
) -> SuiteRunDetailOut:
    row = service.get_run(suite_run_id)
    return SuiteRunDetailOut(
        **_suite_run_out(service, row).model_dump(),
        results=[_result_out(r) for r in service.results(suite_run_id)],
    )


@router.post("/suite-runs/{suite_run_id}/cancel", response_model=SuiteRunOut)
def cancel_suite_run(
    service: ServiceDep, principal: PrincipalDep, suite_run_id: uuid.UUID
) -> SuiteRunOut:
    return _suite_run_out(service, service.cancel(suite_run_id, principal))


# --- comparisons -----------------------------------------------------------------------------


@router.get("/comparisons")
def get_comparison(
    service: ServiceDep,
    _: PrincipalDep,
    baseline_suite_run_id: uuid.UUID,
    candidate_suite_run_id: uuid.UUID,
) -> dict[str, Any]:
    """Pairs the two suite runs by scenario and classifies each pair. Read-only."""
    baseline = service.get_run(baseline_suite_run_id)
    candidate = service.get_run(candidate_suite_run_id)
    comparison = service.comparison(baseline.id, candidate.id)
    return {
        "baseline": _suite_run_out(service, baseline).model_dump(mode="json"),
        "candidate": _suite_run_out(service, candidate).model_dump(mode="json"),
        **comparison.to_json(),
    }
