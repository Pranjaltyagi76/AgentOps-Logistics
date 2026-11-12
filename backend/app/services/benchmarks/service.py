"""Benchmark suites: CRUD, launching suite runs, cancelling them, and comparisons (FR-08).

A suite run creates one ordinary run per scenario and repeat, so traces, scoring and diagnosis
work exactly as for single runs. Launching is all or nothing: the same access checks as a
single run, room in the run queue for every child run, and (for LLM agents) the whole
daily-cap allowance taken up front.
"""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.errors import AppError
from app.db.models import BenchmarkSuite, Run, Scenario, SuiteMembership, SuiteRun
from app.domain.comparison import Comparison, compare
from app.domain.metrics import RunResult, suite_metrics
from app.services.benchmarks.settle import ACTIVE, results_for, settle_suite_run
from app.services.execution.service import RunService

MAX_REPEATS = 3
MAX_SUITE_SCENARIOS = 50


class SuiteSpec(BaseModel):
    """A suite file (data/suites/*.json) or API body: scenario keys or a tag, not both."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9-]{2,60}$")
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(default="", max_length=2000)
    scenario_keys: list[str] | None = Field(default=None, max_length=MAX_SUITE_SCENARIOS)
    tag: str | None = Field(default=None, pattern=r"^[a-z0-9_]{2,40}$")
    pinned_versions: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_source(self) -> "SuiteSpec":
        if (self.scenario_keys is None) == (self.tag is None):
            raise ValueError("give either scenario_keys or tag")
        if self.scenario_keys is not None:
            if not self.scenario_keys:
                raise ValueError("scenario_keys must not be empty")
            if len(set(self.scenario_keys)) != len(self.scenario_keys):
                raise ValueError("scenario_keys must not contain duplicates")
            unknown = set(self.pinned_versions) - set(self.scenario_keys)
            if unknown:
                raise ValueError(f"pinned_versions for keys not in the suite: {sorted(unknown)}")
        elif self.pinned_versions:
            raise ValueError("pinned_versions need scenario_keys")
        return self


class SuiteNotFoundError(AppError):
    status_code = 404
    code = "suite_not_found"


class SuiteConflictError(AppError):
    status_code = 409
    code = "suite_conflict"


class SuiteService:
    def __init__(self, db: Session, runs: RunService) -> None:
        self.db = db
        self.runs = runs

    # --- suites ----------------------------------------------------------------------------

    def list_suites(self, include_archived: bool = False) -> list[BenchmarkSuite]:
        query = select(BenchmarkSuite).order_by(BenchmarkSuite.name)
        if not include_archived:
            query = query.where(BenchmarkSuite.status == "active")
        return list(self.db.scalars(query))

    def get(self, suite_id: uuid.UUID) -> BenchmarkSuite:
        suite = self.db.get(BenchmarkSuite, suite_id)
        if suite is None:
            raise SuiteNotFoundError("Suite not found")
        return suite

    def members(self, suite: BenchmarkSuite) -> list[SuiteMembership]:
        return list(
            self.db.scalars(
                select(SuiteMembership)
                .where(SuiteMembership.suite_id == suite.id)
                .order_by(SuiteMembership.position)
            )
        )

    def spec_of(self, suite: BenchmarkSuite) -> SuiteSpec:
        members = self.members(suite)
        return SuiteSpec(
            name=suite.name,
            title=suite.title,
            description=suite.description,
            scenario_keys=[m.scenario_key for m in members] if suite.tag_filter is None else None,
            tag=suite.tag_filter,
            pinned_versions={
                m.scenario_key: m.pinned_version for m in members if m.pinned_version is not None
            },
        )

    def _write_members(self, suite: BenchmarkSuite, spec: SuiteSpec) -> None:
        for member in self.members(suite):
            self.db.delete(member)
        self.db.flush()
        for position, key in enumerate(spec.scenario_keys or []):
            self.db.add(
                SuiteMembership(
                    suite_id=suite.id,
                    scenario_key=key,
                    pinned_version=spec.pinned_versions.get(key),
                    position=position,
                )
            )

    def _check_keys(self, spec: SuiteSpec) -> None:
        if spec.scenario_keys is None:
            return
        known = set(
            self.db.scalars(
                select(Scenario.scenario_key).where(Scenario.scenario_key.in_(spec.scenario_keys))
            )
        )
        missing = [k for k in spec.scenario_keys if k not in known]
        if missing:
            raise AppError(
                f"Unknown scenario keys: {', '.join(missing)}",
                code="unknown_scenarios",
                status_code=422,
            )

    def create(self, spec: SuiteSpec) -> BenchmarkSuite:
        if self.db.scalar(select(BenchmarkSuite).where(BenchmarkSuite.name == spec.name)):
            raise SuiteConflictError(
                f"A suite named '{spec.name}' already exists", code="suite_exists"
            )
        self._check_keys(spec)
        suite = BenchmarkSuite(
            name=spec.name, title=spec.title, description=spec.description, tag_filter=spec.tag
        )
        self.db.add(suite)
        self.db.flush()
        self._write_members(suite, spec)
        self.db.commit()
        return suite

    def update(self, suite_id: uuid.UUID, spec: SuiteSpec) -> BenchmarkSuite:
        """Suite runs keep the scenario versions they resolved, so editing is always safe."""
        suite = self.get(suite_id)
        if spec.name != suite.name:
            raise SuiteConflictError("A suite's name cannot change", code="suite_name_fixed")
        self._check_keys(spec)
        suite.title, suite.description, suite.tag_filter = spec.title, spec.description, spec.tag
        self._write_members(suite, spec)
        self.db.commit()
        return suite

    def import_many(self, specs: list[dict[str, Any]]) -> list[tuple[str, str]]:
        """Idempotent seeding from data/suites: created / updated / unchanged per suite."""
        outcomes = []
        for raw in specs:
            spec = SuiteSpec.model_validate(raw)
            existing = self.db.scalar(
                select(BenchmarkSuite).where(BenchmarkSuite.name == spec.name)
            )
            if existing is None:
                self.create(spec)
                outcomes.append((spec.name, "created"))
            elif self.spec_of(existing) == spec:
                outcomes.append((spec.name, "unchanged"))
            else:
                self.update(existing.id, spec)
                outcomes.append((spec.name, "updated"))
        return outcomes

    def set_status(self, suite_id: uuid.UUID, status: str) -> BenchmarkSuite:
        suite = self.get(suite_id)
        suite.status = status
        self.db.commit()
        return suite

    def resolve(self, suite: BenchmarkSuite) -> list[Scenario]:
        """The scenario versions a run of this suite uses right now."""
        if suite.tag_filter is not None:
            keys = sorted(
                set(
                    self.db.scalars(
                        select(Scenario.scenario_key).where(
                            Scenario.tags.contains([suite.tag_filter]), Scenario.status == "active"
                        )
                    )
                )
            )
            pinned: dict[str, int | None] = dict.fromkeys(keys)
        else:
            pinned = {m.scenario_key: m.pinned_version for m in self.members(suite)}
        resolved, problems = [], []
        for key, version in pinned.items():
            query = select(Scenario).where(Scenario.scenario_key == key)
            if version is not None:
                query = query.where(Scenario.version == version)
            else:
                query = query.where(Scenario.status == "active").order_by(Scenario.version.desc())
            scenario = self.db.scalars(query.limit(1)).first()
            if scenario is None or scenario.status == "archived":
                problems.append(f"{key}{f' v{version}' if version else ''}")
            else:
                resolved.append(scenario)
        if problems:
            raise SuiteConflictError(
                f"These scenarios are missing or archived: {', '.join(problems)}",
                code="suite_scenarios_unavailable",
            )
        if not resolved:
            raise SuiteConflictError("The suite has no active scenarios", code="suite_empty")
        return resolved

    # --- suite runs ------------------------------------------------------------------------

    def launch(
        self, suite_id: uuid.UUID, agent_id: uuid.UUID, repeats: int, principal: Principal
    ) -> SuiteRun:
        if not 1 <= repeats <= MAX_REPEATS:
            raise AppError(
                f"repeats must be between 1 and {MAX_REPEATS}",
                code="invalid_repeats",
                status_code=422,
            )
        suite = self.get(suite_id)
        if suite.status != "active":
            raise SuiteConflictError("This suite is archived", code="suite_archived")
        agent, config = self.runs.load_agent(agent_id)
        self.runs.check_can_launch(config, principal)
        scenarios = self.resolve(suite)
        total = len(scenarios) * repeats
        if not self.runs.limiter.allow(f"suites:{principal.subject}"):
            raise AppError(
                "Too many suite runs started; wait a minute", code="rate_limited", status_code=429
            )
        self.runs.check_queue_room(total)
        self.runs.consume_llm_runs(config, total)

        suite_run = SuiteRun(
            suite_id=suite.id,
            agent_config_id=agent.id,
            suite_name=suite.name,
            agent_name=agent.name,
            agent_version=agent.version,
            provider=agent.provider,
            status="queued",
            repeats=repeats,
            total_runs=total,
            scenarios_json=[
                {"scenario_key": s.scenario_key, "version": s.version, "scenario_id": str(s.id)}
                for s in scenarios
            ],
            triggered_by_role=principal.role,
            triggered_by=principal.subject,
        )
        self.db.add(suite_run)
        self.db.flush()
        children = [
            self.runs.new_run(
                scenario, agent, config, principal, suite_run_id=suite_run.id, repeat_index=repeat
            )
            for repeat in range(repeats)
            for scenario in scenarios
        ]
        self.db.commit()
        for run in children:
            self.runs.submit(run, config)
        self.db.refresh(suite_run)
        return suite_run

    def get_run(self, suite_run_id: uuid.UUID) -> SuiteRun:
        suite_run = self.db.get(SuiteRun, suite_run_id)
        if suite_run is None:
            raise AppError("Suite run not found", code="suite_run_not_found", status_code=404)
        return suite_run

    def list_runs(
        self, *, suite_id: uuid.UUID | None = None, status: str | None = None, limit: int = 50
    ) -> list[SuiteRun]:
        query = select(SuiteRun).order_by(SuiteRun.created_at.desc())
        if suite_id is not None:
            query = query.where(SuiteRun.suite_id == suite_id)
        if status is not None:
            query = query.where(SuiteRun.status == status)
        return list(self.db.scalars(query.limit(max(1, min(limit, 100)))))

    def progress(self, suite_run_id: uuid.UUID) -> dict[str, int]:
        counts = dict(
            self.db.execute(
                select(Run.status, func.count())
                .where(Run.suite_run_id == suite_run_id)
                .group_by(Run.status)
            ).all()
        )
        done = sum(c for s, c in counts.items() if s not in ACTIVE)
        return {"done": done, "active": sum(counts.get(s, 0) for s in ACTIVE), **counts}

    def cancel(self, suite_run_id: uuid.UUID, principal: Principal) -> SuiteRun:
        suite_run = self.get_run(suite_run_id)
        if not principal.is_owner and suite_run.triggered_by != principal.subject:
            raise AppError(
                "You can only cancel suite runs you started", code="forbidden", status_code=403
            )
        if not suite_run.is_active:
            raise SuiteConflictError(
                f"Suite run is already {suite_run.status}", code="suite_run_not_active"
            )
        self.db.execute(
            update(SuiteRun).where(SuiteRun.id == suite_run_id).values(cancel_requested=True)
        )
        self.db.commit()
        active = list(
            self.db.scalars(
                select(Run.id).where(Run.suite_run_id == suite_run_id, Run.status.in_(ACTIVE))
            )
        )
        for run_id in active:
            run = self.db.get(Run, run_id)
            if run is not None and run.is_active:
                self.runs.cancel(run_id, principal)
        settle_suite_run(self.runs.session_factory, suite_run_id)
        self.db.expire_all()
        return self.get_run(suite_run_id)

    def results(self, suite_run_id: uuid.UUID) -> list[RunResult]:
        self.get_run(suite_run_id)
        return results_for(self.db, suite_run_id)

    def comparison(self, baseline_id: uuid.UUID, candidate_id: uuid.UUID) -> Comparison:
        """Pure over persisted data: loads both suite runs' results and compares them."""
        baseline, candidate = self.get_run(baseline_id), self.get_run(candidate_id)
        base, cand = results_for(self.db, baseline.id), results_for(self.db, candidate.id)
        result = compare(base, cand, suite_metrics(base), suite_metrics(cand))
        for label, suite_run in (("baseline", baseline), ("candidate", candidate)):
            if suite_run.is_active:
                result.warnings.append(f"The {label} suite run is still {suite_run.status}.")
        if baseline.id == candidate.id:
            result.warnings.append("Baseline and candidate are the same suite run.")
        return result
