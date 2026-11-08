"""Scenario catalog: validation, versioning, CRUD, import/export.

Versioning rules (FR-01.6, context/system_design.md §5.4):
- Only the latest version of a scenario can be edited.
- Editing an unlocked version updates it in place; editing a locked version (used in a run)
  creates version + 1 and leaves the old row untouched.
- Import is keyed by (scenario_id, version) from the file and is idempotent.
"""

import base64
import binascii
import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Scenario
from app.domain.sop_catalog import SopCatalog
from app.domain.taxonomy import ScenarioStatus
from app.schemas.scenario import ScenarioSpec, ValidationReport, validate_scenario

MAX_PAGE_SIZE = 100


class ScenarioNotFoundError(AppError):
    status_code = 404
    code = "scenario_not_found"


class ScenarioInvalidError(AppError):
    status_code = 422
    code = "scenario_invalid"

    def __init__(self, report: ValidationReport) -> None:
        super().__init__(
            "Scenario failed validation",
            details={
                "errors": [e.model_dump() for e in report.errors],
                "warnings": [w.model_dump() for w in report.warnings],
            },
        )


class ScenarioConflictError(AppError):
    status_code = 409
    code = "scenario_conflict"


@dataclass(frozen=True)
class ListFilters:
    category: str | None = None
    difficulty: str | None = None
    status: str | None = None
    tag: str | None = None
    q: str | None = None


@dataclass(frozen=True)
class ImportResult:
    scenario_key: str | None
    version: int | None
    outcome: Literal["created", "updated", "unchanged", "error"]
    id: uuid.UUID | None = None
    errors: list[dict[str, str]] | None = None


def encode_cursor(scenario_key: str) -> str:
    return base64.urlsafe_b64encode(scenario_key.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> str:
    try:
        return base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise AppError("Invalid cursor", code="invalid_cursor") from exc


def _normalized(spec: ScenarioSpec) -> dict[str, Any]:
    return spec.model_dump(mode="json")


def canonical_json(row: Scenario) -> dict[str, Any]:
    """Stored JSON in schema field order (JSONB does not preserve key order)."""
    return _normalized(ScenarioSpec.model_validate(row.scenario_json))


def _escape_like(text: str) -> str:
    """Escapes LIKE wildcards so user search text is matched literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ScenarioService:
    def __init__(self, db: Session, catalog: SopCatalog) -> None:
        self.db = db
        self.catalog = catalog

    # --- validation ------------------------------------------------------------------

    def validate(self, data: Any) -> tuple[ScenarioSpec | None, ValidationReport]:
        return validate_scenario(data, self.catalog)

    def _require_valid(self, data: Any) -> ScenarioSpec:
        spec, report = self.validate(data)
        if spec is None:
            raise ScenarioInvalidError(report)
        return spec

    # --- queries -----------------------------------------------------------------------

    def _latest_versions(self) -> Select[tuple[Scenario]]:
        latest = (
            select(Scenario.scenario_key, func.max(Scenario.version).label("max_version"))
            .group_by(Scenario.scenario_key)
            .subquery()
        )
        return select(Scenario).join(
            latest,
            and_(
                Scenario.scenario_key == latest.c.scenario_key,
                Scenario.version == latest.c.max_version,
            ),
        )

    def list_page(
        self, filters: ListFilters, *, limit: int = 20, cursor: str | None = None
    ) -> tuple[list[Scenario], str | None, int]:
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        query = self._latest_versions()
        if filters.category:
            query = query.where(Scenario.category == filters.category)
        if filters.difficulty:
            query = query.where(Scenario.difficulty == filters.difficulty)
        if filters.status:
            query = query.where(Scenario.status == filters.status)
        else:
            query = query.where(Scenario.status != ScenarioStatus.ARCHIVED)
        if filters.tag:
            query = query.where(Scenario.tags.contains([filters.tag]))
        if filters.q:
            pattern = f"%{_escape_like(filters.q.strip())}%"
            query = query.where(
                or_(
                    Scenario.title.ilike(pattern, escape="\\"),
                    Scenario.scenario_key.ilike(pattern, escape="\\"),
                )
            )

        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        if cursor:
            query = query.where(Scenario.scenario_key > decode_cursor(cursor))
        rows = list(self.db.scalars(query.order_by(Scenario.scenario_key).limit(limit + 1)))
        next_cursor = encode_cursor(rows[limit - 1].scenario_key) if len(rows) > limit else None
        return rows[:limit], next_cursor, total

    def get(self, scenario_id: uuid.UUID) -> Scenario:
        row = self.db.get(Scenario, scenario_id)
        if row is None:
            raise ScenarioNotFoundError("Scenario not found")
        return row

    def versions(self, scenario_key: str) -> list[Scenario]:
        return list(
            self.db.scalars(
                select(Scenario)
                .where(Scenario.scenario_key == scenario_key)
                .order_by(Scenario.version.desc())
            )
        )

    def _latest(self, scenario_key: str) -> Scenario | None:
        return self.db.scalar(
            select(Scenario)
            .where(Scenario.scenario_key == scenario_key)
            .order_by(Scenario.version.desc())
            .limit(1)
        )

    def _by_key_version(self, scenario_key: str, version: int) -> Scenario | None:
        return self.db.scalar(
            select(Scenario).where(
                Scenario.scenario_key == scenario_key, Scenario.version == version
            )
        )

    # --- writes ------------------------------------------------------------------------

    def _new_row(self, spec: ScenarioSpec, status: str) -> Scenario:
        row = Scenario(scenario_key=spec.scenario_id, version=spec.version, status=status)
        self._apply(row, spec)
        self.db.add(row)
        return row

    @staticmethod
    def _apply(row: Scenario, spec: ScenarioSpec) -> None:
        row.title = spec.title
        row.category = spec.category.value
        row.difficulty = spec.difficulty.value
        row.tags = list(spec.tags)
        row.scenario_json = _normalized(spec)

    def create(self, data: Any, *, status: str = ScenarioStatus.ACTIVE) -> Scenario:
        spec = self._require_valid(data)
        if self._latest(spec.scenario_id) is not None:
            raise ScenarioConflictError(
                f"Scenario '{spec.scenario_id}' already exists; edit it or clone it instead"
            )
        row = self._new_row(spec, status)
        self.db.commit()
        return row

    def update(
        self, scenario_id: uuid.UUID, data: Any, *, status: str | None = None
    ) -> tuple[Scenario, Literal["updated", "new_version", "unchanged"]]:
        row = self.get(scenario_id)
        latest = self._latest(row.scenario_key)
        assert latest is not None
        if latest.id != row.id:
            raise ScenarioConflictError(
                f"Only the latest version (v{latest.version}) can be edited",
                code="not_latest_version",
            )
        if isinstance(data, dict) and data.get("scenario_id") not in (None, row.scenario_key):
            raise AppError(
                "scenario_id cannot be changed; clone the scenario instead", code="key_mismatch"
            )

        target_version = row.version + 1 if row.is_locked else row.version
        payload = {**data, "scenario_id": row.scenario_key, "version": target_version}
        spec = self._require_valid(payload)
        new_status = status or row.status

        unchanged_json = {**_normalized(spec), "version": row.version} == row.scenario_json
        if unchanged_json and new_status == row.status:
            return row, "unchanged"
        if row.is_locked and not unchanged_json:
            new_row = self._new_row(spec, new_status)
            self.db.commit()
            return new_row, "new_version"
        if not unchanged_json:
            self._apply(row, spec)
        row.status = new_status
        self.db.commit()
        return row, "updated"

    def clone(self, scenario_id: uuid.UUID, new_key: str | None = None) -> Scenario:
        source = self.get(scenario_id)
        key = new_key or self._next_free_key(source.scenario_key)
        if self._latest(key) is not None:
            raise ScenarioConflictError(f"Scenario '{key}' already exists")
        payload = {
            **source.scenario_json,
            "scenario_id": key,
            "version": 1,
            "title": f"{source.title} (copy)"[:160],
        }
        spec = self._require_valid(payload)
        row = self._new_row(spec, ScenarioStatus.DRAFT)
        self.db.commit()
        return row

    def _next_free_key(self, key: str) -> str:
        match = re.match(r"^(?P<base>.+)_(?P<num>\d{3})$", key)
        base = match["base"] if match else key
        existing = set(
            self.db.scalars(
                select(Scenario.scenario_key).where(Scenario.scenario_key.like(f"{base}_%"))
            )
        )
        for number in range(1, 1000):
            candidate = f"{base}_{number:03d}"
            if candidate not in existing:
                return candidate
        raise ScenarioConflictError("No free scenario number left for this base name")

    def set_status(self, scenario_id: uuid.UUID, status: ScenarioStatus) -> list[Scenario]:
        """Archive/restore applies to every version of the scenario."""
        row = self.get(scenario_id)
        rows = self.versions(row.scenario_key)
        for version_row in rows:
            version_row.status = status
        self.db.commit()
        return rows

    def import_many(self, items: list[Any]) -> list[ImportResult]:
        results: list[ImportResult] = []
        for item in items:
            spec, report = self.validate(item)
            if spec is None:
                key = item.get("scenario_id") if isinstance(item, dict) else None
                version = item.get("version") if isinstance(item, dict) else None
                results.append(
                    ImportResult(
                        scenario_key=key if isinstance(key, str) else None,
                        version=version if isinstance(version, int) else None,
                        outcome="error",
                        errors=[e.model_dump() for e in report.errors],
                    )
                )
                continue
            existing = self._by_key_version(spec.scenario_id, spec.version)
            if existing is None:
                row = self._new_row(spec, ScenarioStatus.ACTIVE)
                self.db.flush()
                results.append(ImportResult(spec.scenario_id, spec.version, "created", row.id))
            elif existing.scenario_json == _normalized(spec):
                results.append(
                    ImportResult(spec.scenario_id, spec.version, "unchanged", existing.id)
                )
            elif existing.is_locked:
                results.append(
                    ImportResult(
                        spec.scenario_id,
                        spec.version,
                        "error",
                        existing.id,
                        [
                            {
                                "loc": "version",
                                "msg": "this version is locked; bump the version number",
                            }
                        ],
                    )
                )
            else:
                self._apply(existing, spec)
                results.append(ImportResult(spec.scenario_id, spec.version, "updated", existing.id))
        self.db.commit()
        return results

    def export_latest(self) -> list[dict[str, Any]]:
        query = self._latest_versions().where(Scenario.status != ScenarioStatus.ARCHIVED)
        rows = self.db.scalars(query.order_by(Scenario.scenario_key))
        return [canonical_json(row) for row in rows]
