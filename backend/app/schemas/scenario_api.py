"""Request/response models for the scenario API (separate from the file schema)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.taxonomy import ScenarioStatus
from app.schemas.scenario import ValidationReport


class ScenarioSummaryOut(BaseModel):
    id: uuid.UUID
    scenario_key: str
    version: int
    title: str
    category: str
    difficulty: str
    status: str
    tags: list[str]
    is_locked: bool
    updated_at: datetime


class ScenarioPageOut(BaseModel):
    items: list[ScenarioSummaryOut]
    next_cursor: str | None
    total: int


class ScenarioVersionOut(BaseModel):
    id: uuid.UUID
    version: int
    status: str
    is_locked: bool
    created_at: datetime


class ScenarioDetailOut(ScenarioSummaryOut):
    created_at: datetime
    versions: list[ScenarioVersionOut]
    # Customer message, visible context, mock data, tools, documents, description, as_of.
    visible: dict[str, Any]
    # Ground truth, evaluation, fault injection, author note. Owner only; null for viewers.
    hidden: dict[str, Any] | None
    can_edit: bool


class ScenarioWriteIn(BaseModel):
    scenario: dict[str, Any]
    status: Literal["draft", "active"] | None = None


class ScenarioWriteOut(BaseModel):
    outcome: Literal["created", "updated", "new_version", "unchanged"]
    scenario: ScenarioDetailOut
    warnings: list[dict[str, str]] = Field(default_factory=list)


class CloneIn(BaseModel):
    new_scenario_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*_\d{3}$")


class StatusChangeOut(BaseModel):
    scenario_key: str
    status: ScenarioStatus
    versions_changed: int


class ImportIn(BaseModel):
    scenarios: list[dict[str, Any]] = Field(min_length=1, max_length=200)


class ImportItemOut(BaseModel):
    scenario_key: str | None
    version: int | None
    outcome: Literal["created", "updated", "unchanged", "error"]
    id: uuid.UUID | None = None
    errors: list[dict[str, str]] | None = None


class ImportOut(BaseModel):
    results: list[ImportItemOut]
    created: int
    updated: int
    unchanged: int
    errors: int


class ExportOut(BaseModel):
    exported_at: datetime
    scenarios: list[dict[str, Any]]


ValidateOut = ValidationReport
