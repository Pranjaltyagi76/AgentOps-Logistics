"""Benchmark suites and suite runs (FR-08).

A suite names its scenarios by key (explicit memberships) or by tag. A suite run freezes the
resolved scenario versions in `scenarios_json`, so editing the suite later never changes it.
Each suite run owns one ordinary run per scenario and repeat (`runs.suite_run_id`).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import CreatedAt, UUIDPrimaryKey


class BenchmarkSuite(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "benchmark_suites"
    __table_args__ = (UniqueConstraint("name", name="uq_benchmark_suites_name"),)

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tag_filter: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SuiteMembership(UUIDPrimaryKey, Base):
    __tablename__ = "suite_memberships"
    __table_args__ = (
        UniqueConstraint("suite_id", "scenario_key", name="uq_suite_memberships_suite_key"),
    )

    suite_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("benchmark_suites.id", ondelete="CASCADE"), nullable=False
    )
    scenario_key: Mapped[str] = mapped_column(String(80), nullable=False)
    pinned_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SuiteRun(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "suite_runs"
    __table_args__ = (
        Index("ix_suite_runs_suite_id_created_at", "suite_id", "created_at"),
        Index("ix_suite_runs_status", "status"),
    )

    suite_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("benchmark_suites.id", ondelete="RESTRICT"), nullable=False
    )
    agent_config_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_configs.id", ondelete="RESTRICT"), nullable=False
    )
    suite_name: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_version: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")
    repeats: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False)
    # [{"scenario_key", "version", "scenario_id"}], frozen at launch.
    scenarios_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    evaluator_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    triggered_by_role: Mapped[str] = mapped_column(String(10), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(64), nullable=False)

    @property
    def is_active(self) -> bool:
        return self.status in ("queued", "running")
