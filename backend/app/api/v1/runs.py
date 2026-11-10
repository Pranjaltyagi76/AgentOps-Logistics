"""Run endpoints: launch (202), list, detail, trace (with incremental polling) and cancel.

Any signed-in principal can read runs and launch rule-based runs; LLM runs are owner-only.
Trace payloads are served with person-like fields masked (NFR-06).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import PrincipalDep, SettingsDep
from app.core.redaction import redact_pii
from app.db.models import Run, TraceEvent
from app.db.session import get_db
from app.services.execution.service import RunFilters, RunService

router = APIRouter(prefix="/runs", tags=["runs"])


def get_service(
    request: Request, settings: SettingsDep, db: Annotated[Session, Depends(get_db)]
) -> RunService:
    state = request.app.state
    return RunService(db, settings, state.executor, state.session_factory, state.run_limiter)


ServiceDep = Annotated[RunService, Depends(get_service)]


class RunCreateIn(BaseModel):
    scenario_id: uuid.UUID
    agent_config_id: uuid.UUID


class RunSummaryOut(BaseModel):
    id: uuid.UUID
    status: str
    stop_reason: str | None
    scenario_id: uuid.UUID
    scenario_key: str
    scenario_version: int
    agent_config_id: uuid.UUID
    agent_name: str
    agent_version: int
    provider: str
    root_cause: str | None
    escalation: bool | None
    tool_call_count: int | None
    latency_ms: int | None
    verdict: str | None
    score: float | None
    triggered_by_role: str
    is_demo: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunPageOut(BaseModel):
    items: list[RunSummaryOut]
    next_cursor: str | None


class RunDetailOut(RunSummaryOut):
    steps: int | None
    error_kind: str | None
    error: dict[str, Any] | None
    outcome: dict[str, Any] | None
    actions: list[dict[str, Any]]
    usage: dict[str, Any] | None
    limits: dict[str, Any]
    versions: dict[str, Any]
    cancel_requested: bool
    trace_event_count: int


class TraceEventOut(BaseModel):
    seq: int
    ref: str
    event_type: str
    node: str | None
    tool: str | None
    input: Any
    output: Any
    error: dict[str, Any] | None
    evidence_ids: list[str]
    duration_ms: int | None
    usage: dict[str, Any] | None
    timestamp: datetime


class TraceOut(BaseModel):
    run_id: uuid.UUID
    status: str
    events: list[TraceEventOut]


def _summary(run: Run) -> dict[str, Any]:
    outcome = run.final_outcome_json or {}
    return {
        "id": run.id,
        "status": run.status,
        "stop_reason": run.stop_reason,
        "scenario_id": run.scenario_id,
        "scenario_key": run.scenario_key,
        "scenario_version": run.scenario_version,
        "agent_config_id": run.agent_config_id,
        "agent_name": run.agent_name,
        "agent_version": run.agent_version,
        "provider": run.provider,
        "root_cause": outcome.get("root_cause"),
        "escalation": outcome.get("escalation"),
        "tool_call_count": run.tool_call_count,
        "latency_ms": run.latency_ms,
        "verdict": run.verdict,
        "score": run.score,
        "triggered_by_role": run.triggered_by_role,
        "is_demo": run.is_demo,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def _detail(service: RunService, run: Run) -> RunDetailOut:
    config = run.config_snapshot_json
    return RunDetailOut(
        **_summary(run),
        steps=run.steps,
        error_kind=run.error_kind,
        error=run.error_json,
        outcome=run.final_outcome_json,
        actions=redact_pii(run.actions_json or []),
        usage=run.usage_json,
        limits={k: config.get(k) for k in ("max_steps", "max_tool_calls", "timeout_s")},
        versions=run.versions_json,
        cancel_requested=run.cancel_requested,
        trace_event_count=service.trace_count(run.id),
    )


def _event(event: TraceEvent) -> TraceEventOut:
    return TraceEventOut(
        seq=event.seq,
        ref=f"te:{event.seq}",
        event_type=event.event_type,
        node=event.node_name,
        tool=event.tool_name,
        input=redact_pii(event.input_json),
        output=redact_pii(event.output_json),
        error=event.error_json,
        evidence_ids=list(event.evidence_ids),
        duration_ms=event.duration_ms,
        usage=event.usage_json,
        timestamp=event.timestamp,
    )


@router.post("", response_model=RunDetailOut, status_code=202)
def create_run(service: ServiceDep, principal: PrincipalDep, body: RunCreateIn) -> RunDetailOut:
    run = service.create(body.scenario_id, body.agent_config_id, principal)
    return _detail(service, run)


@router.get("", response_model=RunPageOut)
def list_runs(
    service: ServiceDep,
    _: PrincipalDep,
    status: Annotated[
        str | None, Query(pattern=r"^(queued|running|completed|timed_out|cancelled|errored)$")
    ] = None,
    scenario_key: Annotated[str | None, Query(max_length=80)] = None,
    agent_name: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> RunPageOut:
    filters = RunFilters(status=status, scenario_key=scenario_key, agent_name=agent_name)
    rows, next_cursor = service.list_page(filters, limit=limit, cursor=cursor)
    return RunPageOut(items=[RunSummaryOut(**_summary(r)) for r in rows], next_cursor=next_cursor)


@router.get("/{run_id}", response_model=RunDetailOut)
def get_run(service: ServiceDep, _: PrincipalDep, run_id: uuid.UUID) -> RunDetailOut:
    return _detail(service, service.get(run_id))


@router.get("/{run_id}/trace", response_model=TraceOut)
def get_trace(
    service: ServiceDep,
    _: PrincipalDep,
    run_id: uuid.UUID,
    after_seq: Annotated[int, Query(ge=0, description="Only events after this seq")] = 0,
) -> TraceOut:
    events = service.trace(run_id, after_seq)
    run = service.get(run_id)
    return TraceOut(run_id=run_id, status=run.status, events=[_event(e) for e in events])


@router.post("/{run_id}/cancel", response_model=RunDetailOut)
def cancel_run(service: ServiceDep, principal: PrincipalDep, run_id: uuid.UUID) -> RunDetailOut:
    return _detail(service, service.cancel(run_id, principal))
