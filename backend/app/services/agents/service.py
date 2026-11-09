"""Agent configuration catalog with the same versioning rules as scenarios (FR-03.2):
only the latest version is editable; editing a locked version creates version + 1."""

import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import AgentConfig
from app.schemas.agent_config import AgentConfigSpec


class AgentNotFoundError(AppError):
    status_code = 404
    code = "agent_not_found"


class AgentInvalidError(AppError):
    status_code = 422
    code = "agent_invalid"


class AgentConflictError(AppError):
    status_code = 409
    code = "agent_conflict"


@dataclass(frozen=True)
class AgentImportResult:
    name: str | None
    version: int | None
    outcome: Literal["created", "updated", "unchanged", "error"]
    errors: list[dict[str, str]] | None = None


def parse_spec(data: Any) -> AgentConfigSpec:
    try:
        return AgentConfigSpec.model_validate(data)
    except ValidationError as exc:
        errors = [
            {"loc": ".".join(str(p) for p in e["loc"]) or "(root)", "msg": e["msg"]}
            for e in exc.errors()
        ]
        raise AgentInvalidError(
            "Agent config failed validation", details={"errors": errors}
        ) from exc


def spec_of(row: AgentConfig) -> AgentConfigSpec:
    return AgentConfigSpec.model_validate(row.config_json)


class AgentConfigService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- queries -------------------------------------------------------------------------

    def list_latest(
        self, *, provider: str | None = None, include_archived: bool = False
    ) -> list[AgentConfig]:
        latest = (
            select(AgentConfig.name, func.max(AgentConfig.version).label("v"))
            .group_by(AgentConfig.name)
            .subquery()
        )
        query = select(AgentConfig).join(
            latest, and_(AgentConfig.name == latest.c.name, AgentConfig.version == latest.c.v)
        )
        if provider:
            query = query.where(AgentConfig.provider == provider)
        if not include_archived:
            query = query.where(AgentConfig.status != "archived")
        return list(self.db.scalars(query.order_by(AgentConfig.name)))

    def get(self, agent_id: uuid.UUID) -> AgentConfig:
        row = self.db.get(AgentConfig, agent_id)
        if row is None:
            raise AgentNotFoundError("Agent config not found")
        return row

    def versions(self, name: str) -> list[AgentConfig]:
        return list(
            self.db.scalars(
                select(AgentConfig)
                .where(AgentConfig.name == name)
                .order_by(AgentConfig.version.desc())
            )
        )

    def _latest(self, name: str) -> AgentConfig | None:
        rows = self.versions(name)
        return rows[0] if rows else None

    # --- writes --------------------------------------------------------------------------

    def _new_row(self, spec: AgentConfigSpec, status: str = "active") -> AgentConfig:
        row = AgentConfig(name=spec.name, version=spec.version, status=status)
        self._apply(row, spec)
        self.db.add(row)
        return row

    @staticmethod
    def _apply(row: AgentConfig, spec: AgentConfigSpec) -> None:
        row.description = spec.description
        row.provider = spec.provider
        row.model_id = spec.model_id
        row.prompt_version = spec.prompt_version
        row.config_json = spec.model_dump(mode="json")

    def create(self, data: Any) -> AgentConfig:
        spec = parse_spec({**data, "version": 1} if isinstance(data, dict) else data)
        if self._latest(spec.name) is not None:
            raise AgentConflictError(f"An agent named '{spec.name}' already exists")
        row = self._new_row(spec)
        self.db.commit()
        return row

    def update(
        self, agent_id: uuid.UUID, data: Any
    ) -> tuple[AgentConfig, Literal["updated", "new_version", "unchanged"]]:
        row = self.get(agent_id)
        latest = self._latest(row.name)
        assert latest is not None
        if latest.id != row.id:
            raise AgentConflictError(
                f"Only the latest version (v{latest.version}) can be edited",
                code="not_latest_version",
            )
        if not isinstance(data, dict):
            raise AgentInvalidError("Agent config must be a JSON object")
        if data.get("name") not in (None, row.name):
            raise AppError("name cannot be changed; clone the agent instead", code="name_mismatch")
        target = row.version + 1 if row.is_locked else row.version
        spec = parse_spec({**data, "name": row.name, "version": target})
        if {**spec.model_dump(mode="json"), "version": row.version} == row.config_json:
            return row, "unchanged"
        if row.is_locked:
            new_row = self._new_row(spec, row.status)
            self.db.commit()
            return new_row, "new_version"
        self._apply(row, spec)
        self.db.commit()
        return row, "updated"

    def clone(self, agent_id: uuid.UUID, new_name: str | None = None) -> AgentConfig:
        source = self.get(agent_id)
        name = new_name or self._next_free_name(source.name)
        if self._latest(name) is not None:
            raise AgentConflictError(f"An agent named '{name}' already exists")
        spec = parse_spec({**source.config_json, "name": name, "version": 1})
        row = self._new_row(spec)
        self.db.commit()
        return row

    def _next_free_name(self, name: str) -> str:
        base = re.sub(r"-copy(-\d+)?$", "", name)
        existing = set(
            self.db.scalars(select(AgentConfig.name).where(AgentConfig.name.like(f"{base}-copy%")))
        )
        for number in range(1, 100):
            candidate = f"{base}-copy" if number == 1 else f"{base}-copy-{number}"
            if candidate not in existing:
                return candidate[:61]
        raise AgentConflictError("No free copy name left")

    def set_status(
        self, agent_id: uuid.UUID, status: Literal["active", "archived"]
    ) -> list[AgentConfig]:
        rows = self.versions(self.get(agent_id).name)
        for row in rows:
            row.status = status
        self.db.commit()
        return rows

    def import_many(self, items: list[Any]) -> list[AgentImportResult]:
        results: list[AgentImportResult] = []
        for item in items:
            try:
                spec = parse_spec(item)
            except AgentInvalidError as exc:
                name = item.get("name") if isinstance(item, dict) else None
                results.append(AgentImportResult(name, None, "error", exc.details["errors"]))
                continue
            existing = self.db.scalar(
                select(AgentConfig).where(
                    AgentConfig.name == spec.name, AgentConfig.version == spec.version
                )
            )
            if existing is None:
                self._new_row(spec)
                self.db.flush()
                results.append(AgentImportResult(spec.name, spec.version, "created"))
            elif existing.config_json == spec.model_dump(mode="json"):
                results.append(AgentImportResult(spec.name, spec.version, "unchanged"))
            elif existing.is_locked:
                errors = [{"loc": "version", "msg": "this version is locked; bump the version"}]
                results.append(AgentImportResult(spec.name, spec.version, "error", errors))
            else:
                self._apply(existing, spec)
                results.append(AgentImportResult(spec.name, spec.version, "updated"))
        self.db.commit()
        return results
