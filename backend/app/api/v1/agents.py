"""Agent configuration endpoints. Reads need any session; writes need the owner role."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import OwnerDep, PrincipalDep, SettingsDep
from app.core.errors import AppError
from app.db.models import AgentConfig
from app.db.session import get_db
from app.domain.taxonomy import ToolName
from app.schemas.agent_config import Provider
from app.services.agents.service import AgentConfigService, parse_spec, spec_of
from app.services.execution.service import LLM_RUNS_KEY, usage_today

router = APIRouter(prefix="/agents", tags=["agents"])


def get_service(db: Annotated[Session, Depends(get_db)]) -> AgentConfigService:
    return AgentConfigService(db)


ServiceDep = Annotated[AgentConfigService, Depends(get_service)]


class AgentSummaryOut(BaseModel):
    id: uuid.UUID
    name: str
    version: int
    description: str
    provider: str
    model_id: str
    status: str
    is_locked: bool
    tool_count: int
    updated_at: datetime


class AgentVersionOut(BaseModel):
    id: uuid.UUID
    version: int
    status: str
    is_locked: bool
    created_at: datetime


class AgentDetailOut(AgentSummaryOut):
    created_at: datetime
    config: dict[str, Any]
    versions: list[AgentVersionOut]
    can_edit: bool


class AgentWriteOut(BaseModel):
    outcome: Literal["created", "updated", "new_version", "unchanged"]
    agent: AgentDetailOut


class CloneIn(BaseModel):
    new_name: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{2,60}$")


class ProviderStatus(BaseModel):
    provider: Provider
    label: str
    configured: bool
    available: bool
    note: str
    model: str | None = None  # model used for configs whose model_id is "default"
    daily_cap: int | None = None  # LLM providers only
    runs_left_today: int | None = None  # LLM providers, owner only (viewers can't launch them)


class StatusChangeOut(BaseModel):
    name: str
    status: str
    versions_changed: int


def _summary(row: AgentConfig) -> AgentSummaryOut:
    return AgentSummaryOut(
        id=row.id,
        name=row.name,
        version=row.version,
        description=row.description,
        provider=row.provider,
        model_id=row.model_id,
        status=row.status,
        is_locked=row.is_locked,
        tool_count=len(row.config_json.get("tools", [])),
        updated_at=row.updated_at,
    )


def _detail(service: AgentConfigService, row: AgentConfig, owner: bool) -> AgentDetailOut:
    versions = service.versions(row.name)
    return AgentDetailOut(
        **_summary(row).model_dump(),
        created_at=row.created_at,
        config=spec_of(row).model_dump(mode="json"),
        versions=[
            AgentVersionOut(
                id=v.id,
                version=v.version,
                status=v.status,
                is_locked=v.is_locked,
                created_at=v.created_at,
            )
            for v in versions
        ],
        can_edit=owner and versions[0].id == row.id,
    )


@router.get("", response_model=list[AgentSummaryOut])
def list_agents(
    service: ServiceDep,
    _: PrincipalDep,
    provider: Provider | None = None,
    include_archived: bool = False,
) -> list[AgentSummaryOut]:
    return [
        _summary(r)
        for r in service.list_latest(provider=provider, include_archived=include_archived)
    ]


@router.get("/providers", response_model=list[ProviderStatus])
def provider_status(
    settings: SettingsDep, principal: PrincipalDep, db: Annotated[Session, Depends(get_db)]
) -> list[ProviderStatus]:
    """Whether each provider is usable. Never reveals keys, only whether one is set."""
    gemini_ready = settings.gemini_api_key is not None
    cap = settings.llm_daily_run_cap
    left = max(0, cap - usage_today(db, LLM_RUNS_KEY)) if principal.is_owner else None
    if gemini_ready:
        gemini_note = (
            f"Runs on {settings.gemini_model} (owner only, max {cap} LLM runs per day, "
            f"{settings.gemini_rpm_limit} requests per minute)."
        )
    else:
        gemini_note = "Set GEMINI_API_KEY on the server to enable Gemini agents."
    return [
        ProviderStatus(
            provider="rule_based",
            label="Rule-based (no LLM)",
            configured=True,
            available=True,
            note="Deterministic baseline agents; free and always available.",
        ),
        ProviderStatus(
            provider="gemini",
            label="Google Gemini",
            configured=gemini_ready,
            available=gemini_ready,
            note=gemini_note,
            model=settings.gemini_model,
            daily_cap=cap,
            runs_left_today=left,
        ),
        ProviderStatus(
            provider="openai",
            label="OpenAI",
            configured=settings.openai_api_key is not None,
            available=False,
            note="Optional adapter, planned for later.",
        ),
    ]


@router.get("/tools", response_model=list[str])
def tool_names(_: PrincipalDep) -> list[str]:
    return [t.value for t in ToolName]


@router.post("/validate")
def validate_agent(_: PrincipalDep, config: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
    try:
        parse_spec({**config, "version": config.get("version", 1)})
    except AppError as exc:
        return {"valid": False, "errors": exc.details.get("errors", [])}
    return {"valid": True, "errors": []}


@router.post("", response_model=AgentWriteOut, status_code=201)
def create_agent(
    service: ServiceDep, _: OwnerDep, config: Annotated[dict[str, Any], Body()]
) -> AgentWriteOut:
    row = service.create(config)
    return AgentWriteOut(outcome="created", agent=_detail(service, row, True))


@router.get("/{agent_id}", response_model=AgentDetailOut)
def get_agent(service: ServiceDep, principal: PrincipalDep, agent_id: uuid.UUID) -> AgentDetailOut:
    return _detail(service, service.get(agent_id), principal.is_owner)


@router.patch("/{agent_id}", response_model=AgentWriteOut)
def update_agent(
    service: ServiceDep,
    _: OwnerDep,
    agent_id: uuid.UUID,
    config: Annotated[dict[str, Any], Body()],
    response: Response,
) -> AgentWriteOut:
    row, outcome = service.update(agent_id, config)
    if outcome == "new_version":
        response.status_code = 201
    return AgentWriteOut(outcome=outcome, agent=_detail(service, row, True))


@router.post("/{agent_id}/clone", response_model=AgentWriteOut, status_code=201)
def clone_agent(
    service: ServiceDep,
    _: OwnerDep,
    agent_id: uuid.UUID,
    body: Annotated[CloneIn | None, Body()] = None,
) -> AgentWriteOut:
    row = service.clone(agent_id, body.new_name if body else None)
    return AgentWriteOut(outcome="created", agent=_detail(service, row, True))


@router.post("/{agent_id}/archive", response_model=StatusChangeOut)
def archive_agent(service: ServiceDep, _: OwnerDep, agent_id: uuid.UUID) -> StatusChangeOut:
    rows = service.set_status(agent_id, "archived")
    return StatusChangeOut(name=rows[0].name, status="archived", versions_changed=len(rows))


@router.post("/{agent_id}/restore", response_model=StatusChangeOut)
def restore_agent(service: ServiceDep, _: OwnerDep, agent_id: uuid.UUID) -> StatusChangeOut:
    rows = service.set_status(agent_id, "active")
    return StatusChangeOut(name=rows[0].name, status="active", versions_changed=len(rows))
